# -*- coding: utf-8 -*-
"""設定例。これを config.py にコピーして自分の値を入れる（config.py は公開しない）。"""

SYMBOL = "USD/JPY"

# --- データ源 ---
DATA_SOURCE = "twelvedata"        # "twelvedata"（本番）or "csv"（テスト/バックテスト）
TWELVE_DATA_API_KEY = "YOUR_TWELVE_DATA_KEY"
BARS_5M = 1500                    # 取得する5分足の本数（4Hダウ判定に十分な量）
CSV_PATH = ""                     # DATA_SOURCE="csv" のときの5分足CSVパス

# --- 通知 ---
DISCORD_WEBHOOK_URL = "YOUR_DISCORD_WEBHOOK_URL"

# --- その他 ---
TIMEZONE_SHIFT_HOURS = 9          # データのUTC→JST変換（Dukascopy/TwelveData=UTC基準）
DRY_RUN = False                   # True なら送信せず本文を表示するだけ
