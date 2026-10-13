# Workspace memory bootstrap

Before substantial work, read `/Users/jaredcohen/code/MEMORY.md`, then this project's `.claude/memory/MEMORY.md`. Follow the topic-file index and read only task-relevant topic files.

If this is a Git worktree without local project memory, run `bash /Users/jaredcohen/code/.agents/resolve-project-memory` and read the reported file. If it cannot resolve one, report that gap before making substantial changes. Every delegated agent must do the same.

# Notion task tracking (required)

Whenever a work item is finished (a feature, fix, or other shippable change, usually one commit or merge), record it in Notion right away. Don't wait for the end of the session.

- Add a row to the Notion Tasks data source `collection://49084620-171e-4efb-93e5-f7a216f9cbe9` using the Notion MCP: `Status` = Done, `Source` = Claude Code, `Completed` = today, `Project` = the Projects row whose `Repo Path` matches this repo, and a unique `External ID`. If the item already exists as a task, set it to Done instead of adding a duplicate.
- One task per concrete item, named in plain language for what changed. Don't use internal batch or wave labels ("Wave G2", "B12e") as the task name.
- Use TaskCreate/TaskUpdate for tracked work too. The Stop hook syncs those, but it only sees the main session. Workflow and subagent work doesn't reach it, so the orchestrating session records those items itself.
- Details and IDs: `~/.claude/projects/-Users-jaredcohen-code/memory/notion-projects-db.md`.
