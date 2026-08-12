---
description: |
  コードレビューSkill。差分リスクを自動評価し、方式を振り分ける。
  USE FOR: 実装完了後の品質確認、PR作成前のレビュー、「/review」「コードレビューして」「実装をレビュー」
  DO NOT USE FOR: 軽微なtypo修正・コメント追加のみの変更
---

# Cold Edge コードレビュー・オーケストレーター

## 概要

差分のリスクレベルを自動評価し、以下の3方式を自動振り分けする：

| 方式 | 対象 | レビュアー数 |
|------|------|------------|
| `/review-light` | リスク低（1ファイル・コメント/ログ追加のみ） | 1体（高速・軽量） |
| `/review-standard` | リスク中（通常の機能追加・バグ修正） | 3体並列 |
| `/review-heavy` | リスク高（predict_*.py/gate_*.py/v38_core.py/モデル設定変更） | 6体並列 + Self-Critique |

---

## Step 1: リスク自動評価

以下のコマンドで差分を取得してリスクを評価せよ：

```powershell
git diff --name-only HEAD
git diff --stat HEAD
```

**リスク判定基準:**

```
HIGH リスク条件（いずれか1つでも該当 → /review-heavy）:
  - src/predict_morning.py, src/predict_today.py の変更
  - src/run_forward_test.py, src/evaluate_v38_live.py の変更
  - src/v38_core.py, models/ 配下の設定ファイル変更
  - data/processed/ への書き込みロジックの変更
  - Pydantic スキーマ定義の変更
  - フィルタ条件（距離・場名）の変更

MEDIUM リスク条件（HIGH非該当 & いずれか該当 → /review-standard）:
  - src/ 配下の複数ファイル（2件以上）変更
  - tests/ の変更・追加
  - .claude/rules/ または antigravity_rules/ の変更
  - 新規関数・クラスの追加

LOW リスク（上記非該当 → /review-light）:
  - 1ファイルのみの変更
  - コメント・ドキュメント・ログ文言の変更のみ
  - 設定値の数値変更なし
```

---

## Step 2-A: `/review-light`（低リスク）

1体で5軸チェックリストによるレビューを実施：

```
【5軸チェック】
1. 目的適合性: TASK.mdの要件と一致しているか？
2. 妥当性: lessons.mdの既知の失敗パターンに抵触しないか？
3. 整合性: predict_morning.pyとevaluate_v38_live.pyのロジックが乖離していないか？
4. 品質・運用性: matplotlib使用禁止・文字コード設定・PowerShell専用実行の制約を守っているか？
5. 根拠性: [VERIFIED]/[REASONED]/[ASSUMED]ラベルが適切に付与されているか？
```

出力形式：
```markdown
## レビュー結果（軽量）
- リスクレベル: 🟢 LOW
- 方式: /review-light（1体）
- 問題なし / 要修正箇所: [箇条書き]
```

---

## Step 2-B: `/review-standard`（中リスク）

3体の専門サブエージェントを並列起動し、以下の観点で独立レビューさせる：

```
Reviewer-1（ロジック整合）:
  - 本番（predict_morning.py）と評価（evaluate_v38_live.py）のロジック完全一致確認
  - フェイルセーフ・フィルタ条件が維持されているか

Reviewer-2（テスト・品質）:
  - 既存テストが通るか（pytest コマンドを提示）
  - lessons.md の失敗パターン照合（ブール式簡約・既定値フォールバック・ホールドアウト汚染）

Reviewer-3（セキュリティ・環境）:
  - matplotlib 使用禁止・文字コード設定・NARスクレイピング間隔1.5s守られているか
  - data/raw/ や v38_3_config.json への不正書き込みがないか
```

Aggregator（評価器）が3体の指摘を統合してレポートを出力する。

---

## Step 2-C: `/review-heavy`（高リスク）

6体の専門サブエージェントを並列起動 + Self-Critique：

```
Reviewer-1（本番予測ロジック）: predict_morning.py との整合性
Reviewer-2（評価・検証ロジック）: evaluate_v38_live.py・run_forward_test.py との整合性
Reviewer-3（フィルタ・安全床）: ハードフィルタ（距離・場名）・Circuit Breaker の維持確認
Reviewer-4（データ整合性）: 特徴量の定義・スキーマ・Pydantic バリデーション
Reviewer-5（テスト網羅性）: lessons.mdの失敗パターン全件照合・テストカバレッジ
Reviewer-6（コスト・パフォーマンス）: クエリ効率・メモリ・NARレート制限
```

**Self-Critique（独立検証）:**
6体の指摘を受け取ったAggregatoreが「見落としはないか？」を独立して自己批判的に評価し、最終レポートを作成する。

重大度分類：
- 🔴 CRITICAL: 即時修正必須（ゲート基準・フィルタ・本番ロジックに影響）
- 🟠 HIGH: 修正推奨（テスト欠損・スキーマ違反）
- 🟡 MEDIUM: 要検討（コード品質・将来的リスク）
- 🟢 INFO: 情報提供のみ

---

## Step 3: 出力形式

```markdown
# コードレビュー結果

## サマリー
- リスクレベル: [LOW / MEDIUM / HIGH]
- 使用方式: [/review-light / /review-standard / /review-heavy]
- 変更ファイル数: N
- 重大指摘: [🔴 N件 / 🟠 N件 / 🟡 N件]
- 判定: ✅ マージ可 / ⚠️ 要修正後にマージ / ❌ マージ不可

## 指摘事項
[重大度別箇条書き]

## 検証コマンド（提案）
```powershell
# 推奨テストコマンド
```

## Self-Critique（見落としチェック）
[Aggregatorによる自己批判的評価]
```
