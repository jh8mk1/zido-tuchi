# -*- coding: utf-8 -*-
"""データ取得。5分足を取り、必要な上位足は全てリサンプルで生成する
（5分足があれば15m/1h/4h等はすべて合成できる）。データ源は差し替え可能。
"""
import numpy as np
import pandas as pd
from . import indicators as ind


def load_csv(path, tz_shift_hours=9):
    """過去データCSV（datetime_utc, Open, High, Low, Close）を5分足DFとして読む。"""
    d = pd.read_csv(path, index_col=0, parse_dates=True)
    d.index = d.index + pd.Timedelta(hours=tz_shift_hours)   # UTC -> JST
    d = d[["Open", "High", "Low", "Close"]].dropna()
    return d[~d.index.duplicated(keep="first")].sort_index()


def fetch_twelvedata(symbol, api_key, bars=1500, tz_shift_hours=9):
    """Twelve Data から直近の5分足を取得（本番用・ユーザーのマシンで実行）。"""
    import requests
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": symbol, "interval": "5min", "outputsize": bars,
              "timezone": "UTC", "apikey": api_key, "format": "JSON"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    js = r.json()
    if "values" not in js:
        raise RuntimeError(f"Twelve Data error: {js.get('message', js)}")
    df = pd.DataFrame(js["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float)
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close"})
    df.index = df.index + pd.Timedelta(hours=tz_shift_hours)
    return df[["Open", "High", "Low", "Close"]]


def get_5m(config):
    src = getattr(config, "DATA_SOURCE", "twelvedata")
    if src == "csv":
        return load_csv(config.CSV_PATH, config.TIMEZONE_SHIFT_HOURS)
    df = fetch_twelvedata(config.SYMBOL, config.TWELVE_DATA_API_KEY,
                          getattr(config, "BARS_5M", 5000), config.TIMEZONE_SHIFT_HOURS)
    # 最新の未確定足を落とす（バー単位リペイント防止）。確定済みの直近足で判定する。
    if getattr(config, "DROP_LAST_BAR", True) and len(df) > 1:
        df = df.iloc[:-1]
    return df


def build_frames(df5, timeframes):
    """5分足から必要な時間足の辞書を作る。'5min'はそのまま。"""
    out = {}
    for tf in set(timeframes):
        out[tf] = df5 if tf in ("5min", "5m") else ind.resample(df5, tf)
    return out
