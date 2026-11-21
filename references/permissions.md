# Agent permissions: background for when an operation fails

Normal work uses `permissions_status`, `permissions_apply` and `permissions_test`. The policy is data in [permission-policy.json](permission-policy.json). Read this only to debug.

Files the operations manage:

| Tool | Command rules | Network |
|---|---|---|
| Antigravity CLI | `~/.gemini/antigravity-cli/settings.json` → `permissions.allow/deny`, rules like `command(git push)` | allowed commands run outside the sandbox with network; unlisted ones run sandboxed without network; the web search tool always works |
| Antigravity app | `~/.gemini/config/config.json` → `userSettings.globalPermissionGrants.deny` (app runs Turbo: no deny = it may push) | not sandboxed |
| Codex | `~/.codex/rules/default.rules` → `prefix_rule(pattern = [...], decision = "forbidden")` | `~/.codex/config.toml`: `web_search = "live"`, `[sandbox_workspace_write] network_access = true` |
| Claude (`claude -p`) | `~/.claude/settings.json` → `permissions.deny`, rules like `Bash(git push:*)` | n/a |

Things that bite:
- Rules match whole words from the start of a command, so the policy also denies `git -C`, `git -c`, `git --git-dir`, `git --work-tree`; otherwise `git -C dir push` slips through. Codex cannot match a single token like `--git-dir=/x`.
- Deny > Ask > Allow. Headless Antigravity defaults to `auto` mode; `--mode plan` writes a plan instead of executing, but runs allowed commands while researching.
- A refused command without a deny rule is soft-denied: exit 0 and an empty answer. `thread_ask` reports this as `no_answer` with a hint.
- The parent agent's own policy may refuse to grant extra permissions per call (`agy --settings`). Change the standing policy with the user's approval instead. Never use `--dangerously-skip-permissions`.
- `codex execpolicy check --rules FILE git push origin main` checks a rule by hand; pass separate words (in zsh use `${=cmd}`).
- Restart the Antigravity app if it does not pick up a changed `config.json`.
