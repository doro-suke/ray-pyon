---
description: ゲート評価の実行と結果解釈。「ゲートを確認する」「実弾再開できるか確認」「forward_testを実行する」「今月の統計を見る」などのリクエスト時に使用。
---

# ゲート評価手順

## 実行コマンド

```powershell
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\run_forward_test.py"
```

## 判定基準（全てPASSで実弾再開を検討）

| ゲート | 条件 | 意味 |
|---|---|---|
| G1 | OOS有効月数 >= 12 | 統計的に十分なサンプル期間 |
| G2 | Bootstrap CI下限 > 0 | 95%信頼区間でROIが正 |
| G3 | t統計量 > +1.96 | 月次PnLが統計的に有意に正 |
| G4 | P(ROI>0) > 50% | ベイズ的に正ROIの確率 > 50% |

**G4のみPASSでも実弾再開不可。G1〜G4の全てのPASSが必要。**

## 結果の確認

- 当日レポート: `reports/forward_test_YYYYMMDD.txt`
- 時系列ログ: `data/processed/forward_test_log.csv`（推移確認に使用）

## 月次OOS評価（別コマンド）

```powershell
& "C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe" "C:\Users\Yusuke\Downloads\Cold Edge - 5\src\evaluate_v38_live.py"
```

出力: `reports/v38_live_report_YYYYMMDD.txt`

## 異常検知基準

以下が発生したら全破壊的操作を中断・ユーザーに報告:
- 月次ROIが著しく低下（-50%以下）
- 入力データのパースエラーが連続発生
- `v38_3_config.json` の値が期待値（`show_prob_thresh: 0.40` 等）と異なる
