# -*- coding: utf-8 -*-
"""戦略プラグイン基盤。
- Signal: 通知1件分のデータ（どの手法から来たかを必ず保持）
- Strategy: 全手法の共通インターフェイス
- REGISTRY / register: strategies/ に1ファイル置けば自動登録される仕組み

新しい手法を追加する手順:
  1. strategies/ に xxx.py を作る
  2. Strategy を継承して evaluate() を実装し、@register を付ける
  3. それだけ。run.py が自動で拾って通知に含める。
削除はファイルを消す（または DISABLED=True）だけ。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd

from . import indicators as ind
from . import signals as sig

PIP = 0.01

REGISTRY = {}


def register(cls):
    """戦略クラスを登録するデコレータ。"""
    inst = cls()
    if getattr(inst, "disabled", False):
        return cls
    if inst.id in REGISTRY:
        raise ValueError(f"戦略IDが重複: {inst.id}")
    REGISTRY[inst.id] = inst
    return cls


@dataclass
class Signal:
    strategy_id: str
    strategy_name: str
    kind: str                 # 'デイトレ' / 'スイング' など
    direction: str            # 'buy' / 'sell'
    time: datetime            # シグナル確定足の時刻
    entry: float              # 参考エントリー価格（最終確定足終値）
    sl: float
    sl_pips: float
    tp: Optional[float] = None
    rr: Optional[float] = None
    trail_pips: Optional[float] = None
    adx: Optional[float] = None
    note: str = ""
    extra: dict = field(default_factory=dict)


class Strategy:
    """全手法の基底クラス。サブクラスで属性と build_exit() を定義する。"""
    id = "base"
    name = "base"
    kind = "未分類"
    emoji = "🔔"
    disabled = False

    entry_tf = "5min"
    env_specs = []            # [(tf, detector_spec), ...]
    entry_detector = ("pivot", 5)
    freshness_bars = 45
    exit_kind = "fixed"       # 'fixed'（SL/TP）または 'trailing'
    recent_minutes = None     # 通知の鮮度窓(分)。Noneならconfigの既定値。手法ごとに上書き可

    # ---- サブクラスで実装：イベントから決済情報を埋めて Signal を返す ----
    def build_exit(self, ev, dfs) -> Signal:
        raise NotImplementedError

    # ---- 共通：データから全エントリーイベントを検出し Signal 列にする ----
    def evaluate(self, dfs):
        edf = dfs[self.entry_tf]
        env_dir = sig.combined_env_dir(edf.index, self.env_specs, dfs)
        events = sig.detect_entries(edf, env_dir, self.entry_detector, self.freshness_bars)
        return [self.build_exit(ev, dfs) for ev in events]

    # ---- 共通：保有中ポジションの決済判定（1ポジション制を再現） ----
    # pos: {'direction','entry','sl','entry_time'(iso), 'tp'?(fixed)}
    # 返り: (still_open: bool, exit_info: dict|None)
    def manage(self, pos, dfs):
        edf = dfs[self.entry_tf]
        et = pd.Timestamp(pos["entry_time"])
        sub = edf[edf.index > et]
        if len(sub) == 0:
            return True, None
        highs, lows, idx = sub["High"].values, sub["Low"].values, sub.index
        d, sl = pos["direction"], pos["sl"]

        if self.exit_kind == "fixed":
            tp = pos["tp"]
            for i in range(len(sub)):
                if d == "buy":
                    if lows[i] <= sl:
                        return False, {"price": sl, "time": idx[i], "reason": "SL"}
                    if highs[i] >= tp:
                        return False, {"price": tp, "time": idx[i], "reason": "TP"}
                else:
                    if highs[i] >= sl:
                        return False, {"price": sl, "time": idx[i], "reason": "SL"}
                    if lows[i] <= tp:
                        return False, {"price": tp, "time": idx[i], "reason": "TP"}
            return True, None

        # trailing
        tdf = dfs[self.TRAIL_TF]
        atr_arr = ind.wilder_atr(tdf, 14)
        tidx = tdf.index.values
        stop, ext = sl, pos["entry"]
        for i in range(len(sub)):
            ti = int(np.clip(np.searchsorted(tidx, idx[i].to_datetime64(), side="right") - 1,
                             0, len(atr_arr) - 1))
            td = atr_arr[ti] * self.TRAIL_ATR_MULT
            if not np.isfinite(td) or td <= 0:
                td = abs(pos["entry"] - sl)
            if d == "buy":
                if lows[i] <= stop:
                    return False, {"price": round(stop, 3), "time": idx[i], "reason": "TRAIL"}
                ext = max(ext, highs[i]); stop = max(stop, ext - td)
            else:
                if highs[i] >= stop:
                    return False, {"price": round(stop, 3), "time": idx[i], "reason": "TRAIL"}
                ext = min(ext, lows[i]); stop = min(stop, ext + td)
        return True, None

    def position_from_signal(self, s: "Signal"):
        pos = {"direction": s.direction, "entry": s.entry, "sl": s.sl,
               "entry_time": s.time.isoformat()}
        if s.tp is not None:
            pos["tp"] = s.tp
        return pos

    # 補助
    def _map_index(self, dfs, tf, t):
        arr = dfs[tf].index.values
        return int(np.clip(np.searchsorted(arr, np.datetime64(t), side="right") - 1,
                           0, len(arr) - 1))
