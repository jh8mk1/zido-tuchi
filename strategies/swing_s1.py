# -*- coding: utf-8 -*-
"""スイング手法 S1（honest-S1）＝ V6.1 のエンジンB。

4時間足の単一タイムフレームで完結する。上位足を下位足へ展開しないため、
旧 swing_trailing を実力PF≈0.65 に沈めた MTF ルックアヘッドの経路がそもそも無い。

バックテスト backtest_v6.py の build_engine_b() と同一ロジック:
  - トレンド: 4H終値 > EMA(30) なら上昇 / < なら下降
  - エントリー: 上昇中に RSI(14) が 45 を下から上抜け → 買い（押し戻り）
                下降中に RSI(14) が 55 を上から下抜け → 売り
  - SL: エントリー ∓ ATR(4H,14) × 2.0  ※ATRは単純移動平均版(ind.sma_atr)
  - TP: RR 2.5 固定 / 最大保有 7日(42本) で強制決済 / 同時1ポジション
成績(2015-2026, 往復0.5pips): 全期間PF中央値1.15 / maxDD10%。
※単独運用は非推奨（OOS≈1.0）。エンジンAの分散・安定化用の補助エンジン（手法書§8-2）。
"""
import numpy as np

from engine.strategy import Strategy, Signal, register, PIP
from engine import indicators as ind


@register
class SwingS1(Strategy):
    id = "swing_s1"
    name = "スイングS1（4H EMA30 + RSI押し戻り）"
    kind = "スイング"
    emoji = "🌊"

    entry_tf = "4h"
    env_specs = []             # 単一TFで完結（MTF展開なし＝ルックアヘッド経路なし）
    exit_kind = "fixed"
    recent_minutes = 360       # 数日保有。数時間遅れの通知でも成行で成立する
    max_hold_bars = 42         # 42本 × 4h = 7日で強制決済

    EMA_N = 30
    RSI_N = 14
    RSI_BUY = 45               # 上昇トレンド中にこれを下から上抜け
    RSI_SELL = 55              # 下降トレンド中にこれを上から下抜け
    ATR_N = 14
    ATR_MULT = 2.0
    RR = 2.5

    def evaluate(self, dfs):
        df = dfs[self.entry_tf]
        c = df["Close"].values
        idx = df.index

        atr = ind.sma_atr(df, self.ATR_N)
        rsi = ind.rsi(c, self.RSI_N)
        ema = ind.ema(c, self.EMA_N)

        out = []
        for i in range(1, len(df)):
            if np.isnan(atr[i]) or np.isnan(ema[i]) or np.isnan(rsi[i]) or np.isnan(rsi[i - 1]):
                continue
            if c[i] > ema[i] and rsi[i - 1] < self.RSI_BUY and rsi[i] >= self.RSI_BUY:
                out.append(self._signal(idx[i], "buy", c[i], c[i] - atr[i] * self.ATR_MULT))
            elif c[i] < ema[i] and rsi[i - 1] > self.RSI_SELL and rsi[i] <= self.RSI_SELL:
                out.append(self._signal(idx[i], "sell", c[i], c[i] + atr[i] * self.ATR_MULT))
        return out

    def _signal(self, t, direction, entry, sl):
        sl_dist = abs(entry - sl)
        tp = entry + sl_dist * self.RR if direction == "buy" else entry - sl_dist * self.RR
        return Signal(
            strategy_id=self.id, strategy_name=self.name, kind=self.kind,
            direction=direction, time=t, entry=round(entry, 3),
            sl=round(sl, 3), sl_pips=round(sl_dist / PIP, 1),
            tp=round(tp, 3), rr=self.RR,
            note=(f"4H EMA{self.EMA_N}トレンド + RSI{self.RSI_BUY}/{self.RSI_SELL}押し戻り / "
                  f"SL=ATR×{self.ATR_MULT} / RR{self.RR}固定 / 最大保有7日。"),
        )
