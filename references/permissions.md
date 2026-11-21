# Setting agent permissions

How to control what Antigravity (Gemini), Codex and Claude agents may do on this Mac, so they can research, read and test freely but never push, commit, reset or migrate on their own. Changing another agent's permissions is the user's decision: propose the change, let the user approve it, then apply and test it.

## How the layers work

Every agent call passes through up to four independent layers. A command runs only if all of them let it through.

| Layer | Antigravity | Codex | Claude (`claude -p`) |
|---|---|---|---|
| Standing command rules (allow / ask / deny) | `~/.gemini/antigravity-cli/settings.json`; desktop app: `~/.gemini/config/config.json` | `~/.codex/rules/default.rules` | `~/.claude/settings.json` → `permissions` |
| Sandbox (where it may write, network) | unlisted commands run sandboxed without network; app: `enableTerminalSandbox` | `-s read-only` / `workspace-write` plus `[sandbox_workspace_write]` | per-tool permission prompts; no OS sandbox by default |
| Mode for this call | `--mode plan` / `accept-edits` / `auto` (headless default) | `-c approval_policy='"never"'` for headless | `--permission-mode` |
| The parent agent's own policy | the calling agent (e.g. Claude Code auto mode) may refuse to hand extra permissions to a child per call | same | same |

Deny always wins. Put the dangerous commands on the deny list in every tool and keep the lists identical.

## Baseline policy (in force since 2026-11-21)

Deny everywhere:

```
git push, git commit, git reset, git checkout, git worktree remove,
git -C, git -c, git --git-dir, git --work-tree,
rm -rf, npx prisma migrate, prisma migrate, docker compose down
```

The `git -C/-c/--git-dir/--work-tree` entries matter: rules match the start of the command, so `git -C /some/dir push` would otherwise slip past a `git push` rule. That is exactly how an Antigravity app thread pushed to main on 2026-11-21. Agents run git from inside the repo folder instead.

Allow (Antigravity CLI, so these run outside its sandbox with network): read-only git (`status`, `diff`, `log`, `show`), `ls`, `rg`, `grep`, `cat`, `head`, `wc`, `python3`, `node`, `npx tsx`, `curl`, `npm test` / `npm run build|lint|test`, web reads (`read_url(*)`), reads of `~/Documents/GitHub` and the Antigravity brain folder. `python3` and `node` can run any script; drop them for a strictly read-only agent.

Network: research agents need it. Antigravity's web search tool always works; Codex needs `web_search = "live"`; shell commands that reach the internet or the local DB need Codex `network_access = true` or an Antigravity allow rule.

## Antigravity CLI (`agy -p`)

File: `~/.gemini/antigravity-cli/settings.json` (it does not exist until created).

```json
{
  "permissions": {
    "allow": [
      "read_file(/Users/greinaldpappa/Documents/GitHub)",
      "read_file(/Users/greinaldpappa/.gemini/antigravity/brain)",
      "command(git status)", "command(git diff)", "command(git log)", "command(git show)",
      "command(ls)", "command(rg)", "command(grep)", "command(cat)", "command(head)", "command(wc)",
      "command(python3)", "command(node)", "command(npx tsx)",
      "command(regex:npm (test|run (build|lint|test)))",
      "command(curl)", "read_url(*)"
    ],
    "deny": [
      "command(git push)", "command(git reset)", "command(git checkout)", "command(git worktree remove)",
      "command(git commit)", "command(rm -rf)", "command(npx prisma migrate)", "command(prisma migrate)",
      "command(docker compose down)",
      "command(git -C)", "command(git -c)", "command(git --git-dir)", "command(git --work-tree)"
    ]
  }
}
```

Syntax: `action(target)` with actions `read_file`, `write_file`, `read_url`, `execute_url`, `download_url`, `command`, `mcp`. `command(...)` matches whole words from the start of the command (`command(git push)` matches `git push origin main`). `command(regex:...)` takes a regex. `command(*)` matches everything. Paths are recursive. Order is Deny > Ask > Allow.

Behaviour verified on 2026-11-21:
- Headless `-p` defaults to `auto`. Allowed commands run outside the sandbox with full network. Unlisted commands still run, but in a sandbox without network (no DNS, no localhost). Denied commands are refused with "Matches user-configured deny rule".
- `--mode plan` writes a plan and waits for "Proceed" rather than executing, but it runs allowed commands while researching an answer.
- A command that is refused without a deny rule is soft-denied: exit 0, a notice such as `a tool required the "command" permission`, and possibly an empty answer. Do not treat exit 0 as success.
- Per call, `--settings <json or file>` adds session-only rules. The parent agent's policy may refuse to grant these; then ask the user to extend the standing file instead. Never use `--dangerously-skip-permissions`.
- File writes: start the job with `--mode accept-edits` and a scoped `write_file(<folder>)` rule.

## Antigravity desktop app

File: `~/.gemini/config/config.json`, key `userSettings.globalPermissionGrants` with `allow` / `deny` arrays in the same syntax. The app runs on `permissionPreset: AGENT_PERMISSION_PRESET_TURBO` with eager command auto-execution, so without a deny list an app thread can commit, push and reset without asking. The baseline deny list above is in this file. Rules from this file also apply to CLI runs started with `--app_data_dir=antigravity` (used to talk to app threads). Restart the app after editing if it does not pick the change up.

## Codex

Command rules: `~/.codex/rules/default.rules` (Starlark).

```python
prefix_rule(pattern = ["git", "push"], decision = "forbidden", justification = "Pushing is the user's call.")
prefix_rule(pattern = ["git", "-C"], decision = "forbidden", justification = "Run git from the repo folder; -C hides push/commit/reset.")
# … one line per baseline deny entry
```

`pattern` is a list of whole words matched from the start; `decision` is `forbidden` (or `prompt` / `allow`). Rules apply even inside Codex's `zsh -lc` wrapper. Limitation: a single token like `--git-dir=/x` cannot be matched.

Sandbox and network: `~/.codex/config.toml`.

```toml
web_search = "live"            # built-in web search for research (per call: codex --search exec …)

[sandbox_workspace_write]
network_access = true          # shell may reach the internet and localhost (local Postgres, npm install)
```

`-s workspace-write` limits writes to the `-C` folder; `-s read-only` allows no writes and no shell network. Headless jobs use `-c approval_policy='"never"'`.

## Claude (`claude -p` jobs)

Not configured yet. Claude Code reads `permissions.deny` from `~/.claude/settings.json` (user) or `.claude/settings.json` (project), e.g. `"Bash(git push:*)"`, `"Bash(git commit:*)"`, `"Bash(git -C:*)"`. Use the `update-config` skill to change it rather than editing by hand, and mirror the baseline deny list.

## Testing a change

Always test in a throwaway git repo inside the scratch folder, never in a real project, and delete it afterwards.

1. Validate the files: `python3 -c "import json;json.load(open(PATH))"` for both JSON files.
2. Codex rules without a model call (pass the command as separate words; in zsh an unsplit `$cmd` never matches, use `${=cmd}`):
   `codex execpolicy check --rules ~/.codex/rules/default.rules git -C /x push origin main` → `"decision":"forbidden"`.
3. Real runs: ask each agent to run `git status --short`, `git commit -m test`, `git -C repo commit -m x`, `curl -sS -o /dev/null -w '%{http_code}' https://example.com` and one web search, reporting ALLOWED/BLOCKED and output. Expect status allowed, both commits blocked, curl 200, search works. Confirm with `git log` that no commit exists.
4. Antigravity app rules: move the CLI settings file aside, run the commit test with `--app_data_dir=antigravity`, then put the file back.

Back up `~/.codex/config.toml` and both Antigravity JSON files before editing, read each file before writing it, and change only the permission keys.
