---
description: データパイプライン再構築手順。「DBを再構築する」「master_historyを作り直す」「データパイプラインを実行する」などのリクエスト時に使用。
---

# データパイプライン再構築手順

⚠️ **この操作は既存DBを上書きする。実行前にユーザーの明示的な承認を得ること。**

## Step 1: master DB 構築（全6フェーズ）

```powershell
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\build_master_db.py"
```

出力: `data/processed/master_history.parquet`（113,901行 × 92列）

## Step 2: 訓練用特徴量生成

```powershell
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\make_master_features.py"
```

## Step 3: データ補完・クレンジング（必要時）

```powershell
# 払戻データ補完
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\supplement_payouts.py"

# wide_payout 枠単除去
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\clean_wide_payouts.py"

# DBヘルスチェック
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\audit_database.py"
```

## 注意事項

- **モデル再学習は禁止**: v38_ability.pkl / v38_residual.pkl は凍結済み読み込み専用
- `master_history.parquet` が正。`history_merged.parquet` は旧DBで優先度が低い
- スクレイピング間隔は最低1.5秒（NARサイトへの過負荷を避けること）
