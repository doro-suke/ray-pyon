---
description: |
  Skillの自己改善ループ。会話履歴（JSONL）からSkillへの改善シグナルを抽出し、SKILL.mdを更新するPRを作成する。
  USE FOR: 「Skillを改善して」「スキルを最適化して」「/skill-improve」
  DO NOT USE FOR: 通常のタスク実装・コードレビュー
---

# Skill 自己改善ループ

## 目的

過去の会話履歴に含まれる「Skillへの改善指摘・手戻り・追記指示」を自動抽出し、
対象 `SKILL.md` に反映するための改善PRを作成する。

---

## Step 1: 会話履歴からシグナルを抽出

以下のディレクトリから最新の会話ログを取得する：

```powershell
# Antigravity 会話ログの場所
$logDir = "C:\Users\Yusuke\.gemini\antigravity\brain"
# 最新7日分のトランスクリプトを対象
Get-ChildItem -Path $logDir -Filter "transcript.jsonl" -Recurse |
  Where-Object { $_.LastWriteTime -gt (Get-Date).AddDays(-7) } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 10 | Select-Object FullName, LastWriteTime
```

**抽出すべきシグナル:**
```
1. ユーザーが Skill 呼び出し後に訂正・追記した発言
   例: 「それは違う」「この手順が抜けている」「〜の場合はどうする」
2. Skill が発火しなかったケース（代わりに手動で手順を説明した箇所）
3. 同じ失敗パターンが繰り返されたケース（lessons.md 記録候補）
4. ユーザーが追記・修正した SKILL.md の変更差分
```

---

## Step 2: シグナルを構造化してIssue化

抽出したシグナルを以下の形式で整理する：

```markdown
## Skill改善シグナル（YYYY-MM-DD）

### [Skill名: code_review] シグナル #1
- **種別**: 手順不足（Skill 呼び出し後にユーザーが追加説明）
- **発生日**: YYYY-MM-DD
- **元発言（要約）**: 「git diff --cached も確認してほしい」
- **改善提案**: Step 1 の差分取得コマンドに `git diff --cached` を追記する
- **優先度**: MEDIUM

### [Skill名: daily_batch] シグナル #2
...
```

このシグナルを `docs/skill_improvement_issues.md` に追記する。

---

## Step 3: SKILL.md の改善案を生成

**品質ゲート（変更前に必ず確認）:**
1. `description` の `USE FOR` / `DO NOT USE FOR` は発火条件として明確か？
2. 手順に漏れはないか（ユーザーが毎回口頭で補足している内容が含まれているか）？
3. 200行を超えていないか（超える場合は `references/` に分離する）？

改善案を以下の diff 形式で示す：

```diff
- 旧テキスト
+ 新テキスト
```

---

## Step 4: 3段階品質ゲートで自動検証

改善案を適用する前に以下を確認する：

```
Gate 1 (verify-diff):
  - 改善後の SKILL.md が syntax エラーなく読み込めるか
  - YAML frontmatter が正しいか（description・paths フィールド）

Gate 2 (skill-review):
  - 改善後の Skill が意図した発火条件で起動するか
  - 手順の順序が論理的に正しいか（前のステップの出力を次が使えるか）

Gate 3 (regression-check):
  - 改善前に正しく動いていた既知の使用例が壊れていないか
  - lessons.md の失敗パターンを新たに誘発する記述がないか
```

---

## Step 5: 改善結果を reports/ に記録

```markdown
## Skill改善ログ（YYYY-MM-DD）

| Skill | シグナル数 | 適用件数 | 却下件数 | 結果 |
|-------|-----------|---------|---------|------|
| code_review | 3 | 2 | 1 | ✅ |
| daily_batch | 1 | 1 | 0 | ✅ |
```

記録先: `reports/skill_improvement_log.md`

---

## 実行頻度の推奨

- **手動実行**: 重要な開発セッション完了後
- **定期実行**: 週1回（月曜朝の `run-daily` 実行前）
- **自動トリガー**: lessons.md に新規エントリが3件以上追加されたとき

> [!NOTE]
> Antigravity Routines（Web版 Claude Code の Routines機能相当）を使う場合は、
> このSkillを毎日 `09:00 JST` にトリガーする Routine として設定できる。
> その場合、Step 5 の記録後に Slack/メール通知を追加することを推奨。
