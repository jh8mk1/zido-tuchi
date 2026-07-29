# -*- coding: utf-8 -*-
"""スイング手法：15分ZigZag ABC + 1H/4H MSBダウ二重一致 + 4H ATR×1.5トレーリング。

【停止済み・2026-07】報告値 PF2.30 は MTF ルックアヘッド（上位足の終値=未来 でダウ判定）
の産物であり、正しく検証すると実力は PF≈0.65 の負け手法だった（手法書 §1）。
後継は swing_s1.py（V6.1 エンジンB）。復活させてはならない。記録のためファイルのみ残す。
"""
from engine.strategy import Strategy, Signal, register, PIP
from engine import indicators as ind

ZZ = ("zigzag", 15, 0.27)


@register
class SwingTrailing(Strategy):
    disabled = True            # ルックアヘッド由来の負け手法。復活禁止（上のdocstring参照）
    id = "swing_trailing"
    name = "スイング（ダウ押し目+4H ATRトレーリング）"
    kind = "スイング"
    emoji = "📈"

    entry_tf = "15min"
    env_specs = [("1h", ZZ), ("4h", ZZ)]
    entry_detector = ZZ
    freshness_bars = 45
    exit_kind = "trailing"
    recent_minutes = 360      # 数日保有なので数時間遅れの通知でも成行で成立。GitHub遅延に強くする

    TRAIL_TF = "4h"
    TRAIL_ATR_MULT = 1.5

    def build_exit(self, ev, dfs):
        entry = ev["close"]
        if ev["dir"] == "buy":
            sl = ev["c_price"] - PIP
            sl_dist = entry - sl
        else:
            sl = ev["c_price"] + PIP
            sl_dist = sl - entry

        adf = dfs[self.TRAIL_TF]
        atr_arr = ind.wilder_atr(adf, 14)
        ti = self._map_index(dfs, self.TRAIL_TF, ev["time"])
        atr_val = atr_arr[ti]
        trail_pips = round(atr_val * self.TRAIL_ATR_MULT / PIP, 1) if atr_val == atr_val else None

        return Signal(
            strategy_id=self.id, strategy_name=self.name, kind=self.kind,
            direction=ev["dir"], time=ev["time"], entry=round(entry, 3),
            sl=round(sl, 3), sl_pips=round(abs(sl_dist) / PIP, 1),
            tp=None, trail_pips=trail_pips,
            note=("固定TPなし。初期SLは上記SL（C点基準）。価格が伸びたら "
                  "買い=『最高値−トレール幅』／売り=『最安値＋トレール幅』までSLを更新（有利方向のみ・戻さない）。"
                  "SLに当たったら決済。"),
        )
