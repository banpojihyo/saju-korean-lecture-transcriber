# Repository Agent Rules

## Conversation Logging
- Unless the user explicitly says not to, preserve every user question and assistant answer verbatim in the conversation log.
- Log path: `conversation_logs/YYYY-MM-DD.md` using the Asia/Seoul date.
- If the current day's file does not exist, create it when logging is flushed.
- If the current day's file exists, append new turns.
- Keep each day's conversation log in chronological order. If delayed or pending turns would be out of order, insert or reorder them by timestamp instead of blindly appending them at the end.
- If a turn is only a question/consultation and does not cause any project file changes, do not immediately write that turn to the log file.
- Keep those no-change turns pending, and flush them later together with the next turn that does produce project file changes and will be committed.
- When writing or updating log files, use UTF-8 so Korean text is not corrupted.
- Use UTF-8 for all repository documents that may contain Korean text.

## AGENTS.md Language
- Keep `AGENTS.md` itself in English for instruction stability across environments and agent runtimes.
- Korean may be added only as supplementary examples or clarification when truly needed.

## Git Commit / Push
- After each assistant response, if project files were added/modified/deleted because of the work, select relevant files and run commit + push.
- If the turn is only a question/consultation and no project content changed, do not commit/push.
- Do not include unrelated temporary files in commit.
- Include the conversation log update in the same commit when a file-changing turn is committed.
- Configure Git identity as `banpojihyo <1213hyunsu@naver.com>` before committing when needed.
