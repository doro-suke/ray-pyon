---
description: 日次バッチ実行手順。「今日の予測を出す」「run_daily.batを実行する」「朝の予測を生成する」などのリクエスト時に使用。
---

# 日次運用手順

## 実行コマンド

```powershell
cd "C:\Users\Yusuke\Downloads\Cold Edge - 5"
.\run_daily.bat
```

## 処理の順序（内部）

1. `python src/update_daily_history.py` — 前日レース結果をDBに取り込む
2. `python src/fetch_missing_horses.py` — 欠損馬データを補完
3. `python src/predict_morning.py --date YYYYMMDD` — 本日の予測レポート生成
4. `python src/run_forward_test.py` — ゲート評価 + forward_test_log.csv に追記

## 出力確認先

- 予測レポート: `data/predictions/`
- ゲート評価レポート: `reports/forward_test_YYYYMMDD.txt`
- ゲート蓄積ログ: `data/processed/forward_test_log.csv`

## トラブルシュート

- NARサイトのラグで前日結果が未公開: `update_daily_history.py` は警告を出してスキップする（正常動作）
- エンコーディングエラー: 各スクリプト先頭の `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` を確認
- パスエラー: ダブルクォートでパスを囲んでいるか確認（スペース含むため必須）
