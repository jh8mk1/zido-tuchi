# -*- coding: utf-8 -*-
"""通知ランナー（本番エントリポイント）。
5分足を1回取得 → 必要な上位足を全てリサンプル → 登録済み全戦略を評価 →
新規シグナルだけを手法名つきでDiscord通知 → 重複防止＆フォワードログ。

使い方:
  python run.py                  # 本番（config.py の設定で取得・通知）
  python run.py --test --csv path/to/USDJPY_5m.csv   # ローカルCSVでドライラン
  python run.py --dry-run        # 取得はするが送信せず本文表示
"""
import sys
import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from engine import data as datamod          # noqa: E402
from engine.strategy import REGISTRY        # noqa: E402
import strategies                            # noqa: F401,E402  (自動登録)
import notifier                              # noqa: E402
import statestore                            # noqa: E402


def opposite_holder(states, sid, direction):
    """
    ポートフォリオ層（手法書 §7-1）。

    他エンジンが *逆方向* のポジションを保有中なら (手法ID, その方向) を返す。
    該当なしなら (None, None)。同方向の重複は許可するため None を返す。

    根拠: 重複トレードを3群に分けると赤字は逆方向群のみ（PF0.70）。
    同方向群は全群中で最も勝つ（PF1.48）ので止めてはならない。
    """
    for osid, ost in states.items():
        if osid == sid:
            continue
        p = ost.get("position")
        if p is not None and p["direction"] != direction:
            return osid, p["direction"]
    return None, None


def load_config():
    for name in ("config.py", "config.example.py"):
        p = ROOT / name
        if p.exists():
            spec = importlib.util.spec_from_file_location("fxconfig", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod, name
    raise FileNotFoundError("config.py / config.example.py が見つかりません")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="CSVでドライラン（状態を更新しない）")
    ap.add_argument("--csv", default=None, help="テスト用5分足CSVパス")
    ap.add_argument("--dry-run", action="store_true", help="送信せず本文表示")
    ap.add_argument("--ping", action="store_true", help="Discordにサンプル通知を1件実送信して疎通確認")
    args = ap.parse_args()

    config, cfgname = load_config()

    if args.ping:
        from datetime import datetime
        from engine.strategy import Signal
        sig = Signal(strategy_id="ping", strategy_name="疎通テスト", kind="テスト",
                     direction="buy", time=datetime.now(), entry=160.000,
                     sl=159.800, sl_pips=20.0, tp=160.400, rr=2.0,
                     note="これはWebhook疎通確認のサンプル通知です。")
        ok = notifier.send_discord(config.DISCORD_WEBHOOK_URL, sig, "✅", dry_run=False)
        print("[ping] 送信 " + ("成功" if ok else "失敗"))
        return
    if args.test:
        config.DATA_SOURCE = "csv"
        config.DRY_RUN = True
    if args.csv:                      # --test 以外でもCSVを使えるようにする
        config.DATA_SOURCE = "csv"    # （--dry-run で決済・§7-1ゲートまで通すため）
        config.CSV_PATH = args.csv
    if args.dry_run:
        config.DRY_RUN = True

    print(f"[config] {cfgname} / source={config.DATA_SOURCE} / dry_run={config.DRY_RUN}")
    print(f"[strategies] {', '.join(REGISTRY.keys())}")

    # 全戦略が必要とする時間足を集める
    tfs = {"5min"}
    for s in REGISTRY.values():
        tfs.add(s.entry_tf)
        for tf, _ in s.env_specs:
            tfs.add(tf)
        for attr in ("ADX_TF", "TRAIL_TF"):
            if hasattr(s, attr):
                tfs.add(getattr(s, attr))

    df5 = datamod.get_5m(config)
    dfs = datamod.build_frames(df5, tfs)
    print(f"[data] 5m={len(df5)}本  {df5.index[0]} 〜 {df5.index[-1]} JST")

    # 現在時刻(JST)とFX市場オープン判定
    import datetime as _dt
    import pandas as pd
    now_jst = _dt.datetime.utcnow() + _dt.timedelta(hours=getattr(config, "TIMEZONE_SHIFT_HOURS", 9))
    _wd, _h = now_jst.weekday(), now_jst.hour   # Mon=0 .. Sun=6
    market_closed = (_wd == 5 and _h >= 6) or (_wd == 6) or (_wd == 0 and _h < 7)
    recent_min = getattr(config, "SIGNAL_RECENT_MINUTES", 70)
    print(f"[time] now={now_jst:%Y-%m-%d %H:%M} JST / market_{'CLOSED' if market_closed else 'OPEN'}")
    if market_closed:
        print("[time] FX休場中: 新規エントリー通知はスキップ（決済判定と状態更新のみ）")

    # 全手法のシグナルを先に評価
    evals = {sid: sorted(s.evaluate(dfs), key=lambda x: x.time)
             for sid, s in REGISTRY.items()}

    if args.test:
        for sid, strat in REGISTRY.items():
            sigs = evals[sid]
            if sigs:
                for sig in sigs[-2:]:
                    notifier.send_discord(config.DISCORD_WEBHOOK_URL, sig, strat.emoji, dry_run=True)
                print(f"  [{sid}] 直近シグナル {sigs[-1].time:%Y-%m-%d %H:%M}（テスト表示・状態未更新）")
            else:
                print(f"  [{sid}] シグナルなし（テスト）")
        return

    # ============================================================
    # パス1: 全手法の決済判定を先に済ませる
    #   ポートフォリオ層（パス2）が「他エンジンの現在の保有方向」を見るため、
    #   決済済みのポジションを保有中と誤認しないよう順序を分ける。
    # ============================================================
    states = {}
    for sid, strat in REGISTRY.items():
        st = statestore.get(sid)
        if st["position"] is not None:
            still, ex = strat.manage(st["position"], dfs)
            if not still:
                virtual = st["position"].get("virtual", False)
                if not virtual:
                    notifier.send_exit(config.DISCORD_WEBHOOK_URL, strat, st["position"], ex,
                                       dry_run=config.DRY_RUN)
                statestore.log_exit(sid, strat.name, strat.kind, st["position"], ex)
                st["position"] = None
                tagv = "（仮想・通知なし）" if virtual else ""
                print(f"  [{sid}] 決済目安到達{tagv}: {ex['reason']} @ {ex['price']}")
        states[sid] = st

    # ============================================================
    # パス2: 新規エントリー（ポートフォリオ層のゲートつき）
    # ============================================================
    total_new = 0
    total_veto = 0
    for sid, strat in REGISTRY.items():
        sigs = evals[sid]
        edf = dfs[strat.entry_tf]
        st = states[sid]
        latest_iso = sigs[-1].time.isoformat() if sigs else st["last_seen"]

        if st["position"] is None and sigs:
            last_seen = st["last_seen"]
            if last_seen is None:
                print(f"  [{sid}] 初回起動: ベースライン設定")
            else:
                new = [s for s in sigs if s.time.isoformat() > last_seen]
                # 鮮度判定: 「最新足から」と「実時刻(now)から」の両方で rmin 分以内。
                # 厳しい方(=より新しい方)を採用。これで週末や遅延実行での古いシグナル誤通知を防ぐ。
                # 窓は手法ごと（スイングは広め=遅延に強い、デイトレは狭め）。
                rmin = strat.recent_minutes or recent_min
                cutoff_bar = edf.index[-1] - pd.Timedelta(minutes=rmin)
                cutoff_wall = pd.Timestamp(now_jst) - pd.Timedelta(minutes=rmin)
                cutoff = max(cutoff_bar, cutoff_wall)
                recent = [s for s in new if s.time >= cutoff]
                if market_closed:
                    recent = []   # 休場中は新規通知しない（状態は下で更新）
                if recent:
                    sig = recent[-1]
                    holder, hdir = opposite_holder(states, sid, sig.direction)
                    if holder is not None:
                        # 【手法書§7-1】逆方向の重複は建てない。
                        # ただしポジション枠は「仮想ポジション」として埋める。
                        # バックテスト apply_position_rule はエンジン内部の仮想ポジションを
                        # そのまま進める前提で検証しており、ここでフラットに戻すと
                        # 直後の別シグナルを拾って挙動がズレるため。
                        pos = strat.position_from_signal(sig)
                        pos["virtual"] = True
                        st["position"] = pos
                        statestore.log_veto(sig, holder, hdir)
                        total_veto += 1
                        print(f"  [{sid}] §7-1で見送り: {sig.direction} "
                              f"（{holder}が{hdir}を保有中）→ 仮想ポジションで枠を確保")
                    else:
                        notifier.send_discord(config.DISCORD_WEBHOOK_URL, sig, strat.emoji,
                                              dry_run=config.DRY_RUN)
                        statestore.log_entry(sig)
                        st["position"] = strat.position_from_signal(sig)
                        total_new += 1
                        print(f"  [{sid}] 新規エントリー通知 {sig.direction} {sig.time:%m-%d %H:%M}")
                else:
                    print(f"  [{sid}] 新規なし（フラット）")
        elif st["position"] is not None:
            tagv = "（仮想）" if st["position"].get("virtual") else ""
            print(f"  [{sid}] 保有中{tagv}につき新規シグナル抑制")

        st["last_seen"] = latest_iso
        statestore.put(sid, st)

    print(f"[done] 新規エントリー通知 計{total_new}件 / §7-1見送り {total_veto}件")


if __name__ == "__main__":
    main()
