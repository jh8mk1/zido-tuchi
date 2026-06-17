# -*- coding: utf-8 -*-
"""Discord通知。どの手法から来たシグナルかを必ず明示する。"""
import json
import urllib.request

DIR_JP = {"buy": "買い 🟢", "sell": "売り 🔴"}
COLOR = {"buy": 0x2ecc71, "sell": 0xe74c3c}


def format_signal(sig):
    """1シグナルを人が読める本文に整形（手法名つき）。"""
    lines = [
        f"{DIR_JP.get(sig.direction, sig.direction)}  USD/JPY",
        f"参考エントリー: {sig.entry}",
        f"SL: {sig.sl}  （SL幅 {sig.sl_pips} pips）",
    ]
    if sig.tp is not None:
        lines.append(f"TP: {sig.tp}  （RR {sig.rr}）")
    if sig.trail_pips is not None:
        lines.append(f"トレール幅: {sig.trail_pips} pips（4H ATR×1.5）")
    if sig.adx is not None:
        lines.append(f"ADX(1H): {sig.adx}")
    lines.append(f"シグナル足: {sig.time:%Y-%m-%d %H:%M} JST")
    if sig.note:
        lines.append(f"📝 {sig.note}")
    return "\n".join(lines)


def build_embed(sig, emoji="🔔"):
    return {
        "title": f"{emoji} [{sig.kind}] {sig.strategy_name}",
        "description": format_signal(sig),
        "color": COLOR.get(sig.direction, 0x95a5a6),
        "footer": {"text": f"strategy_id: {sig.strategy_id}"},
    }


def send_exit(webhook_url, strat, pos, exitinfo, dry_run=False):
    """決済目安到達の通知（保有していたポジションが手仕舞いラインに到達）。"""
    title = f"🏁 [{strat.kind}] {strat.name} — 決済目安"
    desc = (f"{DIR_JP.get(pos['direction'], pos['direction'])} を手仕舞い\n"
            f"理由: {exitinfo['reason']}  /  目安価格: {exitinfo['price']}\n"
            f"エントリー: {pos['entry']}（{pos['entry_time'][:16].replace('T',' ')}）\n"
            f"到達足: {exitinfo['time']:%Y-%m-%d %H:%M} JST")
    embed = {"title": title, "description": desc, "color": 0x95a5a6,
             "footer": {"text": f"strategy_id: {strat.id}"}}
    if dry_run or not webhook_url or webhook_url.startswith("YOUR_"):
        print("----- [DRY-RUN] 決済通知 -----")
        print(title); print(desc); print("------------------------------")
        return True
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "fx-notify/1.0 (+https://github.com)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status in (200, 204)


def send_discord(webhook_url, sig, emoji="🔔", dry_run=False):
    embed = build_embed(sig, emoji)
    if dry_run or not webhook_url or webhook_url.startswith("YOUR_"):
        print("----- [DRY-RUN] Discord通知 -----")
        print(embed["title"])
        print(embed["description"])
        print("--------------------------------")
        return True
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "fx-notify/1.0 (+https://github.com)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status in (200, 204)
