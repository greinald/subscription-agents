# Provider adapters and account sessions

Verified locally on 2026-11-15. Model catalogs, versions, and entitlements can change; query the installed CLI rather than assuming these examples are permanent.

## Claude

`claude auth status --json` can verify account authentication without reading credentials. A restrictive execution sandbox can hide keychain access and report logged out even when the host session works; check through authorized host execution before resetting login. The tested session reported Claude Pro (`authMethod: claude.ai`). Claude Code 2.1.325 successfully ran exact model `claude-opus-5-5` with `--effort high`.

The old globally installed 2.0.8 was incompatible with Node 25 and too old for Opus 5.5. If a newer binary is needed, report that requirement or use a caller-supplied executable; do not silently change the requested model. Temporary runtime installation is owned scratch and must be removed after its jobs exit, unless deliberately installed as a maintained tool with user authorization.

Headless form:

```text
claude -p --model MODEL --effort LEVEL --output-format stream-json --verbose --permission-mode plan -- < prompt.txt
```

Use `acceptEdits` only for an authorized builder. `allowed_tools` maps to Claude's `--allowedTools` preapproval list; it is not a tool-removal list or an OS sandbox. `write_mode=False` selects plan mode for research. Provider permissions do not inherit Mac administrator privileges. `--agents`, `--allowedTools`, and `--mcp-config` accept values that can consume a positional prompt: place `--` before stdin input. A custom agent with `model: inherit` inherits the selected model. Connect MCP servers only when needed and authorized; Xcode's local bridge is `/usr/bin/xcrun mcpbridge` on this Mac. Never use a permission bypass to make an unattended task succeed.

Sources: [Claude Code CLI](https://code.claude.com/docs/en/cli-reference), [headless use](https://code.claude.com/docs/en/headless), [model configuration](https://code.claude.com/docs/en/model-config).

### Xcode permission delegation

Xcode identifies the signed client, so permission granted to Codex does not automatically approve Claude Code. After the child calls `XcodeOpenWorkspace`, use `xcrun mcp-server status --format json` to inspect the pending request and its signing identity. The official scoped approval is `sudo xcrun mcp-server approve REQUEST_ID --for-24-hours` (or a deliberate persistent grant). The project folder also needs permission. Inspect the real service outside a restrictive execution sandbox; an isolated status query can misleadingly report that no service is running.

The parent may approve the specific request when authorized and administrator access is available. If `sudo -n` says a password is required, report that limitation; never claim the child was approved. An already-approved parent can perform the child's Xcode review itself. Do not enable blanket permission for all agents as a routine workaround. `xcrun mcp-server --help` is the local source for supported approval commands.

## Gemini through Antigravity

The working Google route on this Mac is `~/.gemini/bin/agy` (1.5.9), even though it is absent from PATH. `agy models` succeeded using the existing keyring session. A read-only call to `gemini-3.8-flash-low` returned `CONNECTION_OK`. The precise Google subscription tier was not independently established.

```text
agy --model MODEL --mode plan --output-format json --print-timeout 45s -p PROMPT
```

Model/effort options include `--model`, `--effort`, and model IDs returned by `agy models`. Resume uses `--conversation ID`. Use `accept-edits` only for authorized edits. Keep `--settings` changes session-local. Existing account login should be reused; do not switch to a Gemini API-key provider just to bypass an account problem. A separate Gemini CLI installation is unnecessary when this route meets the task.

An effort suffix in a model ID must agree with `--effort`: changing `gemini-3.8-flash-low` to medium effort also requires explicitly selecting `gemini-3.8-flash-medium`. The harness rejects conflicting pairs before starting a job. It never silently changes an exact model ID.

### Headless file and command permissions

`--mode accept-edits` alone does not preapprove reads outside the workspace or terminal commands. Pass session-only `agy_settings={"permissions":{"allow":[...]}}` through `start_agent`/`resume_agent`. Use explicit `read_file(/path)`, `write_file(/path)`, and `command(prefix)` rules for the task's sources, images, owned run root and required commands. Relative paths match workspace roots. On macOS, grant canonical real paths as well as visible aliases when necessary: `/var/folders/...` resolves to `/private/var/folders/...`, and an allow rule for only the former was observed to be denied. Use `os.path.realpath` when preparing path rules. Keep global settings unchanged and retain existing deny/ask policies. See [Google's permission documentation](https://antigravity.google/docs/permissions?tab=cli).

Observed behavior: headless agy can return exit 0 and `status: SUCCESS` with an empty response and nonempty `denied_actions`. The harness treats this as failure and retains the action names. Inspect the requested scope, then resume the same conversation with the necessary authorized rules. Do not use permission bypass flags or claim success from the status field alone. If exact denied command details are unavailable, ask the child to return a structured request naming the command before attempting it.

### Talking to an existing Antigravity desktop-app thread

A thread the user started in the Antigravity app (ID like `fd9a3bbf-…`; its files are in `~/.gemini/antigravity/brain/<ID>/`) is stored in the app's data directory `antigravity`. The CLI defaults to `antigravity-cli`, so `agy --conversation <ID>` alone fails with `trajectory not found`. Pass the app data directory (a hidden flag, the same one the running app hub uses):

```text
~/.gemini/bin/agy --app_data_dir=antigravity --conversation <ID> --mode plan -p PROMPT
```

Verified 2026-11-21 while the desktop app hub was running. The message lands in that thread, so the user sees it in the app (with `/plan` prefixed in plan mode), and the agent answers with its full thread context. The answer is printed on stdout. The thread's log is also at `~/.gemini/antigravity/brain/<ID>/.system_generated/logs/transcript.jsonl` (`PLANNER_RESPONSE` rows carry `content`; tool steps show denied actions).

- Read the thread first (last `USER_INPUT` and `PLANNER_RESPONSE` rows) so the question targets what that agent actually claimed.
- Open with who is writing ("This is Claude, writing at the user's request"), state concrete facts with file paths, and ask numbered questions with a word limit. Use `--mode plan` and say "no file edits" unless edits are authorized.
- If the agent's answer is empty because a command was refused, resume the same conversation and tell it to use only `read_file`, or ask the user to extend the allow list. Permission files, modes, sandbox and network behaviour: [permissions](permissions.md).
- The CLI bridge (`agent_tools.py follow_up`) only resumes jobs it started; use the command above for app threads.

Observed catalog examples: `gemini-4-argon-high`, `gemini-4-hydrogen-xhigh`, `gemini-3.8-flash-low`. Query the live catalog before selecting an unfamiliar ID.

Sources: [Antigravity CLI installation and account authentication](https://antigravity.google/docs/install?tab=cli), [CLI overview](https://antigravity.google/docs/cli/overview/), [Gemini CLI account authentication](https://geminicli.com/docs/get-started/authentication/).

## Codex

`codex login status` reported “Logged in using ChatGPT.” Version 0.169.0 ran a successful `gpt-6-sol` probe. The app-bundled fallback executable is `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`; inspect local help when adapting another installed version.

```text
codex exec --json --skip-git-repo-check -C WORKDIR -s read-only -c approval_policy='"never"' -m MODEL -c model_reasoning_effort='"high"' PROMPT
```

Use argv arrays in code; the quoting above illustrates shell use. Redirect unused stdin to avoid hanging. Explicit authorized builders can use `workspace-write`. `-a` is a global CLI option, not an `exec` option; configuration overrides work for noninteractive use. Resume uses the recorded session ID; verify resume-specific flags because its grammar differs from `exec`. Do not use `--ephemeral` when follow-up turns are required.

Command rules (`~/.codex/rules/default.rules`), sandbox modes, web search and shell network (`~/.codex/config.toml`): [permissions](permissions.md).

Check model availability locally (`codex debug models` where supported). The native collaboration tool's model list does not determine what a separately authenticated Codex CLI can run.

Sources: [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [CLI reference](https://learn.chatgpt.com/docs/cli/reference), [authentication](https://learn.chatgpt.com/docs/auth), [security and approvals](https://learn.chatgpt.com/docs/agent-approvals-security).

## Shared rules

Use argv lists and stdin, never interpolated shell commands. Do not print tokens or read raw authentication stores. Prevent API-key environment overrides when subscription use was requested without modifying the caller's environment. Provider JSON errors count as failures even when exit code is zero. CLI usage fields may show nominal API-equivalent costs; those figures alone do not establish actual subscription billing.
