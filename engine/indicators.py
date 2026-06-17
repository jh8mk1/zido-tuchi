# -*- coding: utf-8 -*-
"""共有テクニカル指標・山谷検出。バックテストと本番で同一コードを使う唯一の正。
スイング/デイトレ両手法、将来の手法追加もすべてここを参照する。
"""
import numpy as np
import pandas as pd

PIP = 0.01


# ----------------------------------------------------------------
# リサンプル
# ----------------------------------------------------------------
def resample(df, rule):
    return df.resample(rule).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    ).dropna()


# ----------------------------------------------------------------
# 山谷検出器（どちらも確定ベース・リペイントなし）
#   返り値: [{'type':'H'/'L', 'price':float, 'bar':int, 'confirmed':int}, ...]
# ----------------------------------------------------------------
def pivots(df, n=3):
    """前後n本比較。確定バー = i+n。"""
    h, l = df["High"].values, df["Low"].values
    out, N = [], len(df)
    for i in range(n, N - n):
        wh = h[i - n:i + n + 1]
        if h[i] == wh.max() and (wh == h[i]).sum() == 1:
            out.append({"type": "H", "price": float(h[i]), "bar": i, "confirmed": i + n})
        wl = l[i - n:i + n + 1]
        if l[i] == wl.min() and (wl == l[i]).sum() == 1:
            out.append({"type": "L", "price": float(l[i]), "bar": i, "confirmed": i + n})
    out.sort(key=lambda s: (s["confirmed"], s["bar"]))
    return out


def zigzag(df, length=15, fib_factor=0.27):
    """EmreKb方式（Fib Factor）。v1から不変。"""
    highs, lows, n = df["High"].values, df["Low"].values, len(df)
    out = []
    if n < length:
        return out
    ih, il = int(np.argmax(highs[:length])), int(np.argmin(lows[:length]))
    trend = 1 if ih >= il else -1
    hv, hp = highs[ih], ih
    lv, lp = lows[il], il
    for i in range(length, n):
        wh = highs[i - length + 1:i + 1].max()
        wl = lows[i - length + 1:i + 1].min()
        to_up, to_dn = highs[i] >= wh, lows[i] <= wl
        prev = trend
        if trend == 1 and to_dn:
            ws = hv - lv
            if ws > 0 and (hv - lows[i]) / ws >= fib_factor:
                trend = -1
        elif trend == -1 and to_up:
            ws = hv - lv
            if ws > 0 and (highs[i] - lv) / ws >= fib_factor:
                trend = 1
        if prev == 1 and trend == -1:
            out.append({"type": "H", "price": float(hv), "bar": hp, "confirmed": i})
            lv, lp = lows[i], i
        elif prev == -1 and trend == 1:
            out.append({"type": "L", "price": float(lv), "bar": lp, "confirmed": i})
            hv, hp = highs[i], i
        else:
            if trend == 1 and highs[i] > hv:
                hv, hp = highs[i], i
            elif trend == -1 and lows[i] < lv:
                lv, lp = lows[i], i
    return out


def make_detector(spec):
    """spec例: ('pivot', 5) / ('zigzag', 15, 0.27)。新手法はここに種類を足すだけ。"""
    kind = spec[0]
    if kind == "pivot":
        n = spec[1]
        return lambda df: pivots(df, n)
    if kind == "zigzag":
        length, fib = spec[1], spec[2]
        return lambda df: zigzag(df, length, fib)
    raise ValueError(f"unknown detector spec: {spec}")


# ----------------------------------------------------------------
# 交互整列（同種連続は極値のみ残す）
# ----------------------------------------------------------------
def alternate(sw):
    if not sw:
        return []
    r = [sw[0]]
    for s in sw[1:]:
        last = r[-1]
        if s["type"] == last["type"]:
            if (s["type"] == "H" and s["price"] >= last["price"]) or \
               (s["type"] == "L" and s["price"] <= last["price"]):
                r[-1] = s
        else:
            r.append(s)
    return r


# ----------------------------------------------------------------
# ダウ方向 MSB方式：各バーの 'up'/'down'/'range' を O(n) で
# ----------------------------------------------------------------
def dow_msb_series(df, swings):
    closes, n = df["Close"].values, len(df)
    states = np.empty(n, dtype=object)
    active, ptr, lh, ll = [], 0, None, None
    for i in range(n):
        while ptr < len(swings) and swings[ptr]["confirmed"] <= i:
            s = swings[ptr]; ptr += 1
            if active and active[-1]["type"] == s["type"]:
                last = active[-1]
                if (s["type"] == "H" and s["price"] >= last["price"]) or \
                   (s["type"] == "L" and s["price"] <= last["price"]):
                    active[-1] = s
            else:
                active.append(s)
            if active[-1]["type"] == "H":
                lh = active[-1]["price"]
                ll = active[-2]["price"] if len(active) >= 2 else ll
            else:
                ll = active[-1]["price"]
                lh = active[-2]["price"] if len(active) >= 2 else lh
        cur = closes[i]
        if lh is not None and ll is not None:
            states[i] = "up" if cur > lh else ("down" if cur < ll else "range")
        elif lh is not None:
            states[i] = "up" if cur > lh else "range"
        elif ll is not None:
            states[i] = "down" if cur < ll else "range"
        else:
            states[i] = "range"
    return states


# ----------------------------------------------------------------
# ハイブリッド型ダウ（将来の手法用。HH/HL認定 + キーレベル否定）
#   返り値: states配列 + key_level配列（押し安値/戻り高値）
# ----------------------------------------------------------------
def dow_hybrid_series(df, swings):
    closes, n = df["Close"].values, len(df)
    states = np.empty(n, dtype=object)
    keylv = np.full(n, np.nan)
    ptr, last_type = 0, None
    pH = lH = pL = lL = None
    trend = "range"
    for i in range(n):
        while ptr < len(swings) and swings[ptr]["confirmed"] <= i:
            s = swings[ptr]; ptr += 1
            if last_type == s["type"]:
                if s["type"] == "H":
                    if lH is None or s["price"] >= lH:
                        lH = s["price"]
                else:
                    if lL is None or s["price"] <= lL:
                        lL = s["price"]
            else:
                if s["type"] == "H":
                    pH, lH = lH, s["price"]
                else:
                    pL, lL = lL, s["price"]
                last_type = s["type"]
        c = closes[i]
        if pH is not None and pL is not None:
            if trend == "up" and c < lL:
                trend = "range"
            elif trend == "down" and c > lH:
                trend = "range"
            if trend == "range":
                if lH > pH and lL > pL and c > lH:
                    trend = "up"
                elif lH < pH and lL < pL and c < lL:
                    trend = "down"
        states[i] = trend
        keylv[i] = lL if trend == "up" else (lH if trend == "down" else np.nan)
    return states, keylv


# ----------------------------------------------------------------
# ATR（Wilder平滑）
# ----------------------------------------------------------------
def wilder_atr(df, n=14):
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = np.full(len(tr), np.nan)
    if len(tr) > n:
        atr[n] = tr[1:n + 1].mean()
        for i in range(n + 1, len(tr)):
            atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


# ----------------------------------------------------------------
# ADX（EWM, Wilder相当）
# ----------------------------------------------------------------
def adx(df, n=14):
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    up = np.diff(h, prepend=h[0]); dn = -np.diff(l, prepend=l[0])
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr_ = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values
    safe = np.where(atr_ == 0, np.nan, atr_)
    pdi = 100 * pd.Series(plus).ewm(alpha=1 / n, adjust=False).mean().values / safe
    mdi = 100 * pd.Series(minus).ewm(alpha=1 / n, adjust=False).mean().values / safe
    dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, np.nan, pdi + mdi)
    return pd.Series(dx).ewm(alpha=1 / n, adjust=False).mean().values


# ----------------------------------------------------------------
# ABCパターン（交互整列済みリストに対して）
# ----------------------------------------------------------------
def check_abc(sw, direction):
    for k in range(len(sw) - 1, 1, -1):
        C, B, A = sw[k], sw[k - 1], sw[k - 2]
        if direction == "buy":
            if A["type"] == "L" and B["type"] == "H" and C["type"] == "L" and C["price"] > A["price"]:
                return B, C
        else:
            if A["type"] == "H" and B["type"] == "L" and C["type"] == "H" and C["price"] < A["price"]:
                return B, C
    return None, None
