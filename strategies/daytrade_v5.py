# -*- coding: utf-8 -*-
"""デイトレ手法 v5（honest-v5）：correct-dow ABC + ADXレジームフィルタ。

v4 の MTF ルックアヘッド（上位足の終値=未来 でダウ判定）を排除し、上位足の確定
スイング水準を『現在の5m終値』と比較してダウを判定する（correct-dow-5m）。その上で
過熱トレンド(ADX>32)を回避する単一フィルタ [15,32] を足した正直な手法。

バックテスト strategies/v4_honest.py（構成 F2_ADX[15,32]）と同一ロジック:
  - 環境: 15分/1時間 ZigZag(15,0.27) の確定水準 vs 現在5m終値 が共に上/下
  - エントリー: 5分 Pivot(N=5) の ABC（C確定45本以内）→ 5m終値がB点をブレイク
  - フィルタ: ADX(1時間,14) が 15〜32、JST 07:00〜23:59 のみ、同時1ポジション
  - 決済: SL=C∓1pip / TP=2.0R 固定・時間決済なし
成績(2015-2026, 往復0.5pips): 全期間PF1.24 / OOS(2022-)PF1.73。実戦期待値はPF1.2〜1.3。
"""
import numpy as np
from collections import defaultdict

from engine.strategy import Strategy, Signal, register, PIP
from engine import indicators as ind
from engine import signals as sig

ZZ = ("zigzag", 15, 0.27)


@register
class DaytradeV5(Strategy):
    id = "daytrade_v5"
    name = "デイトレv5（honest-dow ABC + ADXレジーム）"
    kind = "デイトレ"
    emoji = "🎯"

    entry_tf = "5min"
    env_specs = [("15min", ZZ), ("1h", ZZ)]
    entry_detector = ("pivot", 5)
    freshness_bars = 45
    exit_kind = "fixed"
    recent_minutes = 20        # 浅いSLのデイトレは遅延通知だと約定がズレる。古いものは弾く

    # ADXレジームフィルタ（1時間足・エントリー可否）
    ADX_TF = "1h"
    ADX_MIN = 15
    ADX_MAX = 32
    RR = 2.0                   # 固定（v4のADX適応RRは廃止）
    HOUR_START = 7             # JST 07:00〜23:59 のみエントリー
    HOUR_END = 23

    # ---- ABC の B上抜け基準/SL基準(C価格) を各バーに事前展開（v4_honest._precompute_abc 同一） ----
    def _precompute_abc(self, df5):
        n = len(df5)
        within = self.freshness_bars
        sw = ind.pivots(df5, self.entry_detector[1])
        byconf = defaultdict(list)
        for s in sw:
            byconf[s["confirmed"]].append(s)
        bB = np.full(n, np.nan); bC = np.full(n, np.nan)
        sB = np.full(n, np.nan); sC = np.full(n, np.nan)
        active = []
        for i in range(n):
            if i in byconf:
                for s in byconf[i]:
                    if active and active[-1]["type"] == s["type"]:
                        last = active[-1]
                        if (s["type"] == "H" and s["price"] >= last["price"]) or \
                           (s["type"] == "L" and s["price"] <= last["price"]):
                            active[-1] = s
                    else:
                        active.append(s)
                B, C = ind.check_abc(active, "buy")
                if B is not None and C["confirmed"] == i:
                    e = min(i + within, n - 1)
                    bB[i:e + 1] = B["price"]; bC[i:e + 1] = C["price"]
                B2, C2 = ind.check_abc(active, "sell")
                if B2 is not None and C2["confirmed"] == i:
                    e = min(i + within, n - 1)
                    sB[i:e + 1] = B2["price"]; sC[i:e + 1] = C2["price"]
        return bB, bC, sB, sC

    # ---- 全エントリーイベントを検出し Signal 列にする（base.evaluate を上書き） ----
    def evaluate(self, dfs):
        edf = dfs[self.entry_tf]
        c5 = edf["Close"].values
        idx = edf.index
        n = len(edf)

        env = sig.correct_dow_env_dir(edf, self.env_specs, dfs)          # 'up'/'down'/'range'
        udf = dfs[self.ADX_TF]
        adx5 = sig.lag_broadcast(ind.adx(udf, 14), idx, udf.index)       # 1本ラグの確定ADX
        bB, bC, sB, sC = self._precompute_abc(edf)
        hours = idx.hour.values

        out = []
        for i in range(1, n):
            if not (self.HOUR_START <= hours[i] <= self.HOUR_END):
                continue
            a = adx5[i]
            if np.isnan(a) or a < self.ADX_MIN or a > self.ADX_MAX:
                continue
            if env[i] == "up" and not np.isnan(bB[i]):
                if c5[i] > bB[i] and c5[i - 1] <= bB[i]:                 # B点の上抜け（新規クロス）
                    sl = bC[i] - PIP
                    if sl < c5[i]:
                        out.append(self._signal(idx[i], "buy", c5[i], sl, a))
            elif env[i] == "down" and not np.isnan(sB[i]):
                if c5[i] < sB[i] and c5[i - 1] >= sB[i]:
                    sl = sC[i] + PIP
                    if sl > c5[i]:
                        out.append(self._signal(idx[i], "sell", c5[i], sl, a))
        return out

    def _signal(self, t, direction, entry, sl, adx_val):
        sl_dist = abs(entry - sl)
        tp = entry + sl_dist * self.RR if direction == "buy" else entry - sl_dist * self.RR
        return Signal(
            strategy_id=self.id, strategy_name=self.name, kind=self.kind,
            direction=direction, time=t, entry=round(entry, 3),
            sl=round(sl, 3), sl_pips=round(sl_dist / PIP, 1),
            tp=round(tp, 3), rr=self.RR,
            adx=round(float(adx_val), 1) if not np.isnan(adx_val) else None,
            note=(f"honest-dow ABC / ADX{self.ADX_MIN}〜{self.ADX_MAX}レジーム / "
                  f"RR{self.RR}固定。SL/TP到達まで保有（時間決済なし）。"),
        )
