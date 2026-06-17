# -*- coding: utf-8 -*-
"""ABC押し目エントリーの検出（アーミング状態機械）。
バックテストの run ループと同一ロジック。本番は「最後に確定した足で
新規シグナルが出たか」を見るために、検出されたエントリーイベント列を返す。
"""
import numpy as np
from . import indicators as ind


def combined_env_dir(entry_index, env_specs, dfs):
    """エントリー足の各バーについて、複数の環境足ダウが全て一致した方向を返す。
    env_specs: [(tf, detector_spec), ...]  例 [("15min",("zigzag",15,0.27)),("1h",...)]
    全て 'up' なら 'up'、全て 'down' なら 'down'、それ以外 'range'。
    """
    n = len(entry_index)
    per_env = []
    for tf, det_spec in env_specs:
        edf = dfs[tf]
        det = ind.make_detector(det_spec)
        states = ind.dow_msb_series(edf, det(edf))
        # エントリー足タイムスタンプ → 直近確定の環境足インデックス
        m = np.clip(np.searchsorted(edf.index.values, entry_index.values, side="right") - 1,
                    0, len(edf) - 1)
        per_env.append(states[m])
    out = np.empty(n, dtype=object)
    for i in range(n):
        dirs = {e[i] for e in per_env}
        if dirs == {"up"}:
            out[i] = "up"
        elif dirs == {"down"}:
            out[i] = "down"
        else:
            out[i] = "range"
    return out


def detect_entries(entry_df, env_dir, detector_spec, freshness_bars):
    """エントリー足上の全エントリーイベントを返す。
    返り値: [{'bar','time','dir','b_price','c_price','close'}, ...]
    """
    det = ind.make_detector(detector_spec)
    sw = det(entry_df)
    closes = entry_df["Close"].values
    highs = entry_df["High"].values
    lows = entry_df["Low"].values
    idx = entry_df.index
    n = len(entry_df)

    active, ptr = [], 0
    buy_armed = sell_armed = False
    bB = bBb = bC = None
    sB = sBb = sC = None
    events = []

    for i in range(n):
        while ptr < len(sw) and sw[ptr]["confirmed"] <= i:
            s = sw[ptr]; ptr += 1
            if active and active[-1]["type"] == s["type"]:
                last = active[-1]
                if (s["type"] == "H" and s["price"] >= last["price"]) or \
                   (s["type"] == "L" and s["price"] <= last["price"]):
                    active[-1] = s
            else:
                active.append(s)

        if buy_armed and bC is not None and lows[i] < bC:
            buy_armed = False
        if sell_armed and sC is not None and highs[i] > sC:
            sell_armed = False

        d = env_dir[i]
        if d == "up":
            sell_armed = False
            B, C = ind.check_abc(active, "buy")
            if B is not None:
                fresh = C["confirmed"] >= i - freshness_bars
                if not buy_armed and fresh:
                    buy_armed, bB, bBb, bC = True, B["price"], B["bar"], C["price"]
                elif buy_armed and B["bar"] != bBb and fresh:
                    bB, bBb, bC = B["price"], B["bar"], C["price"]
                elif buy_armed and B["bar"] == bBb and C["price"] > bC and fresh:
                    bC = C["price"]
            if buy_armed and closes[i] > bB:
                events.append({"bar": i, "time": idx[i], "dir": "buy",
                               "b_price": bB, "c_price": bC, "close": float(closes[i])})
                buy_armed = False
        elif d == "down":
            buy_armed = False
            B, C = ind.check_abc(active, "sell")
            if B is not None:
                fresh = C["confirmed"] >= i - freshness_bars
                if not sell_armed and fresh:
                    sell_armed, sB, sBb, sC = True, B["price"], B["bar"], C["price"]
                elif sell_armed and B["bar"] != sBb and fresh:
                    sB, sBb, sC = B["price"], B["bar"], C["price"]
                elif sell_armed and B["bar"] == sBb and C["price"] < sC and fresh:
                    sC = C["price"]
            if sell_armed and closes[i] < sB:
                events.append({"bar": i, "time": idx[i], "dir": "sell",
                               "b_price": sB, "c_price": sC, "close": float(closes[i])})
                sell_armed = False

    return events
