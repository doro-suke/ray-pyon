# /check-gate — Safe Gate (DoD) & Code Health Checker

本コマンドは、Cold Edge プロジェクトにおける開発タスク完了前の安全ゲート（DoD 4条件）およびコード・設定の健全性を一括検証するコマンドである。

## 実行手順

1. **設定ファイルの整合性チェック (Settings Audit)**
   - `.claude/settings.json` (Git共通) の `permissions.deny` 設定が、`.claude/settings.local.json` 等によって無効化または競合していないか検証すること。

2. **コード整形 ＆ リント (Format & Lint Step)**
   - 以下のコマンドを PowerShell から実行し、コードのスタイル整形と静的解析を行うこと：
     ```powershell
     ruff format src/ tests/
     ruff check src/ tests/
     ```

3. **DoD 4条件の客観的検証 (Evaluator Execution)**
   - 以下のテストスイートを実行し、テストが 100% 通過することを確認すること：
     ```powershell
     C:\Users\Yusuke\anaconda3\envs\keiba_ai_env\python.exe -m pytest tests/
     ```

4. **検証結果のまとめ**
   - 実行結果を客観的ログとして整理し、`[VERIFIED]` ステータスラベルを添えて報告すること。
