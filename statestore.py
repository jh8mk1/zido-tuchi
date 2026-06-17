# -*- coding: utf-8 -*-
"""重複通知の防止＋ポジション状態＋フォワード検証ログ。
- state/state.json : 手法ごとに {last_seen, position} を保存（1ポジション制の再現）
- logs/signals.csv  : 通知した全エントリー/決済を追記（フォワード検証用）
"""
import json
import csv
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
STATE_DIR = BASE / "state"
LOG_DIR = BASE / "logs"
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = LOG_DIR / "signals.csv"


def load_all():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_all(d):
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def get(sid):
    return load_all().get(sid, {"last_seen": None, "position": None})


def put(sid, st):
    d = load_all()
    d[sid] = st
    save_all(d)


def log_entry(sig):
    _log_row(["ENTRY", sig.strategy_id, sig.strategy_name, sig.kind, sig.direction,
              f"{sig.time:%Y-%m-%d %H:%M}", sig.entry, sig.sl, sig.sl_pips,
              sig.tp if sig.tp is not None else "",
              sig.rr if sig.rr is not None else "",
              sig.trail_pips if sig.trail_pips is not None else "",
              sig.adx if sig.adx is not None else "", ""])


def log_exit(sid, name, kind, pos, exitinfo):
    _log_row(["EXIT", sid, name, kind, pos["direction"],
              f"{pos['entry_time'][:16].replace('T', ' ')}", pos["entry"], pos["sl"], "",
              pos.get("tp", ""), "", "", "",
              f"{exitinfo['reason']}@{exitinfo['price']} ({exitinfo['time']:%m-%d %H:%M})"])


def _log_row(row):
    LOG_DIR.mkdir(exist_ok=True)
    new = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["通知時刻", "種類", "手法ID", "手法名", "種別", "方向", "エントリー足/決済",
                        "参考エントリー", "SL", "SL幅pips", "TP", "RR", "トレール幅pips",
                        "ADX", "決済情報"])
        w.writerow([datetime.now().isoformat(timespec="seconds")] + row)
