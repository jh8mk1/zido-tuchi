# FX シグナル通知システム

USD/JPY の複数手法を**1つのbotで並走監視**し、シグナルが出たらどの手法から来たかを明示して Discord に通知する。手法はプラグイン式で、**1ファイル追加するだけで増え、消すだけで減る**。バックテストと本番が同じ戦略コード（`engine/`）を共有するので、検証と運用がズレない。

## 現在の登録手法

| 手法ID | 種別 | 内容 | 全期間PF / σ |
|---|---|---|---|
| `daytrade_v4` | デイトレ | 5分ピボN=5 ABC + 15分/1H ダウ二重一致 + ADX適応RR | 1.37 / 0.17 |
| `swing_trailing` | スイング | 15分ZigZag ABC + 1H/4H ダウ二重一致 + 4H ATR×1.5トレール | 2.30 / 0.87 |

## ディレクトリ構成

```
notify_system/
├─ run.py                 # 本番エントリポイント（5分足取得→全手法評価→通知）
├─ config.example.py      # 設定例（config.py にコピーして値を入れる）
├─ notifier.py            # Discord通知（手法名タグつき）
├─ statestore.py          # 重複防止・ポジション状態・フォワードログ
├─ engine/                # ★共有エンジン（バックテストと本番で共用する唯一の正）
│   ├─ indicators.py      #   ZigZag / ピボット / MSBダウ / ハイブリッドダウ / ATR / ADX / ABC
│   ├─ signals.py         #   ABC押し目エントリーの検出（アーミング状態機械）
│   ├─ data.py            #   5分足取得（Twelve Data/CSV）＋上位足リサンプル
│   └─ strategy.py        #   Strategy基底クラス・Signal・自動登録レジストリ・決済管理
├─ strategies/            # ★手法プラグイン（ここに足す/消すだけ）
│   ├─ daytrade_v4.py
│   └─ swing_trailing.py
├─ state/                 # 自動生成: ポジション状態（state.json）
└─ logs/                  # 自動生成: フォワード検証ログ（signals.csv）
```

## セットアップ

```bash
cd notify_system
pip3 install requests pandas numpy
cp config.example.py config.py     # config.py に自分の値を入れる
```

`config.py` に設定する値:
- `TWELVE_DATA_API_KEY` … Twelve Data の無料APIキー
- `DISCORD_WEBHOOK_URL` … 通知先チャンネルの Webhook URL

## 動作確認（送信せずに本文だけ表示）

```bash
# 手元の5分足CSVでドライラン（最新シグナルの通知文をプレビュー）
python3 run.py --test --csv ../USDJPY_5m_2015_2026.csv

# 本番設定のデータ取得はするが、送信はしない
python3 run.py --dry-run
```

## 本番実行

```bash
python3 run.py
```

動作ロジック:
1. 5分足を1回だけ取得し、15分/1H/4H を全てリサンプルで生成
2. 登録された全手法を評価
3. **1ポジション制**: 保有中の手法は、決済目安（SL/TP/トレール）への到達を判定して「決済通知」。フラットな手法だけ新規エントリーを探す
4. 新規エントリーが直近確定足で出ていれば、手法名つきで Discord 通知＋ `logs/signals.csv` に記録
5. 初回起動時は通知せずベースライン設定（過去シグナルの一斉通知を防止）

## 手法を追加する

`strategies/my_strategy.py` を作る:

```python
from engine.strategy import Strategy, Signal, register, PIP
from engine import indicators as ind

ZZ = ("zigzag", 15, 0.27)

@register
class MyStrategy(Strategy):
    id = "my_strategy"              # 一意なID（通知の strategy_id に出る）
    name = "私の新手法"
    kind = "デイトレ"               # 通知タグ
    emoji = "🚀"

    entry_tf = "5min"               # エントリー判定の足
    env_specs = [("1h", ZZ)]        # 環境認識（複数なら全一致が条件）
    entry_detector = ("pivot", 3)   # ('pivot', N) または ('zigzag', length, fib)
    freshness_bars = 45
    exit_kind = "fixed"             # 'fixed'(SL/TP) または 'trailing'

    def build_exit(self, ev, dfs):
        entry = ev["close"]
        sl = ev["c_price"] - PIP if ev["dir"] == "buy" else ev["c_price"] + PIP
        sl_dist = abs(entry - sl)
        tp = entry + sl_dist*2 if ev["dir"]=="buy" else entry - sl_dist*2
        return Signal(strategy_id=self.id, strategy_name=self.name, kind=self.kind,
                      direction=ev["dir"], time=ev["time"], entry=round(entry,3),
                      sl=round(sl,3), sl_pips=round(sl_dist/PIP,1), tp=round(tp,3), rr=2.0)
```

これだけ。`run.py` が自動で拾う。**削除はファイルを消すか `disabled = True` を付けるだけ。**

トレーリング型にする場合は `exit_kind = "trailing"` とし、`TRAIL_TF`（例 `"4h"`）と `TRAIL_ATR_MULT`（例 `1.5`）を定義する（`swing_trailing.py` を参照）。

## 自動実行（5分間隔）

### 方式A: Mac の launchd（現行・推奨）
`launchd/com.fxnotify.plist` を `~/Library/LaunchAgents/` に置き、パスを自分の環境に書き換えてから:
```bash
launchctl load ~/Library/LaunchAgents/com.fxnotify.plist
```
5分ごとに `run.py` を実行する。Macが起きている必要がある。

### 方式B: GitHub Actions（Mac非依存・無料・このリポジトリのルート=notify_system想定）
`.github/workflows/notify.yml` で30分ごとに実行する。Mac不要で24時間動く。
GitHub Actionsの既知の弱点を3点とも対策済み:
- **自動停止（60日無活動）**: `keepalive-workflow` でスケジュールを生かし続ける
- **cronの遅延/スキップ**: 30分間隔＋鮮度窓70分の冗長化で1回飛んでも取りこぼさない
- **状態の喪失**: 毎回 `state/state.json` と `logs/signals.csv` をリポジトリにコミットして保持

セットアップ:
1. `notify_system/` をGitHubリポジトリにして push（`config.py` は `.gitignore` 済みなので鍵は上がらない）
2. リポジトリの Settings → Secrets and variables → Actions に登録:
   - `TWELVE_DATA_API_KEY`
   - `DISCORD_WEBHOOK_URL`
3. Actionsタブから手動実行（Run workflow）で初回動作を確認（初回はベースライン設定で通知なしが正常）
4. 以後30分ごとに自動実行。実際の通知は次にシグナルが出たときから

注意: **公開リポジトリ推奨**（Actions実行時間が無制限）。非公開だと無料枠2000分/月のため、cronを `0 * * * *`（毎時=毎月約1080分）に下げること。`state.json`/`signals.csv` には鍵も口座情報も含まれない。
launchd と二重起動すると同じシグナルが二重通知されるので、GitHubに移すなら launchd は `launchctl unload` で止めること。

## 注意

- 通知は「手動エントリーの判断材料」。自動発注はしない。届いたらチャートで最終確認してから入る。
- 実戦期待値は各手法書の数字より控えめに。1%リスクのフォワードテストから開始し、`logs/signals.csv` の実績で昇格判断する。
- `state/state.json` を消すと全手法がベースラインに戻る（次回起動から再カウント）。
