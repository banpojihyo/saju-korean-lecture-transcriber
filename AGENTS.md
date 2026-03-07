# Repository Agent Rules

## Conversation Logging
- Unless the user explicitly says not to, save every user question and assistant answer verbatim.
- Log path: `conversation_logs/YYYY-MM-DD.md` (Asia/Seoul date).
- If today's file does not exist, create it.
- If today's file exists, append new turns.

## Git Commit / Push
- After each assistant response, if project files were added/modified/deleted because of the work, select relevant files and run commit + push.
- If the turn is only a question/consultation and no project content changed, do not commit/push.
- Do not include unrelated temporary files in commit.
