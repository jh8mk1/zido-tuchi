# -*- coding: utf-8 -*-
"""スイング手法：15分ZigZag ABC + 1H/4H MSBダウ二重一致 + 4H ATR×1.5トレーリング。
全期間PF 2.30 / σ 0.87 / 11年プラス。固定TPなし＝トレールで伸ばす。"""
from engine.strategy import Strategy, Signal, register, PIP
from engine import indicators as ind

ZZ = ("zigzag", 15, 0.27)


@register
class SwingTrailing(Strategy):
    id = "swing_trailing"
    name = "スイング（ダウ押し目+4H ATRトレーリング）"
    kind = "スイング"
    emoji = "📈"

    entry_tf = "15min"
    env_specs = [("1h", ZZ), ("4h", ZZ)]
    entry_detector = ZZ
    freshness_bars = 45
    exit_kind = "trailing"

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
            note=("固定TPなし。初期トレールSL=エントリー∓トレール幅。"
                  "以後は直近高値/安値の更新ごとにトレールを引き上げ/引き下げる（戻さない）。"),
        )
