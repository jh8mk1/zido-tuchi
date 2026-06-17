# -*- coding: utf-8 -*-
"""デイトレ手法 v4：5分ピボットN=5 ABC + 15分/1H MSBダウ二重一致 + ADX適応RR。
全期間PF 1.37 / σ 0.17 / 12年全プラス。"""
from engine.strategy import Strategy, Signal, register, PIP
from engine import indicators as ind

ZZ = ("zigzag", 15, 0.27)


@register
class DaytradeV4(Strategy):
    id = "daytrade_v4"
    name = "デイトレv4（ダウ押し目+ADX適応RR）"
    kind = "デイトレ"
    emoji = "⚡"

    entry_tf = "5min"
    env_specs = [("15min", ZZ), ("1h", ZZ)]
    entry_detector = ("pivot", 5)
    freshness_bars = 45
    exit_kind = "fixed"

    # ADX適応RR
    ADX_TF = "1h"
    ADX_THRESH = 30
    RR_LOW = 2.0     # ADX <= 30
    RR_HIGH = 1.5    # ADX > 30

    def build_exit(self, ev, dfs):
        entry = ev["close"]
        if ev["dir"] == "buy":
            sl = ev["c_price"] - PIP
            sl_dist = entry - sl
        else:
            sl = ev["c_price"] + PIP
            sl_dist = sl - entry

        # ADX（1時間足・シグナル時点で確定済みの値）
        adf = dfs[self.ADX_TF]
        adx_arr = ind.adx(adf, 14)
        ai = self._map_index(dfs, self.ADX_TF, ev["time"])
        adx_val = float(adx_arr[ai]) if adx_arr[ai] == adx_arr[ai] else None  # NaN除け

        rr = self.RR_HIGH if (adx_val is not None and adx_val > self.ADX_THRESH) else self.RR_LOW
        if ev["dir"] == "buy":
            tp = entry + sl_dist * rr
        else:
            tp = entry - sl_dist * rr

        return Signal(
            strategy_id=self.id, strategy_name=self.name, kind=self.kind,
            direction=ev["dir"], time=ev["time"], entry=round(entry, 3),
            sl=round(sl, 3), sl_pips=round(abs(sl_dist) / PIP, 1),
            tp=round(tp, 3), rr=rr, adx=round(adx_val, 1) if adx_val is not None else None,
            note=f"ADX{('>30→RR1.5' if rr==self.RR_HIGH else '≤30→RR2.0')}。SL/TP到達まで保有（時間決済なし）。",
        )
