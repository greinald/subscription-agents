---
name: subscription-agents
description: Call Claude Code, Codex, or Google Antigravity through installed account-authenticated CLIs for delegated work, follow-up turns, and result collection.
---

# Subscription agents

Use the small command interface in [scripts/agent_tools.py](scripts/agent_tools.py). **Run it; do not read its Python source for normal work.** It prints one JSON result with the answer, job status, and paths needed for review. Read [the advanced reference](references/harness.md) only for an operation absent from this interface or to debug a demonstrated bridge problem.

| Operation | What it does |
|---|---|
| `run` | Starts a provider turn. Returns the answer directly if it finishes within `wait_seconds` (default 55), or a pending `job_id`. |
| `collect` | Waits for a pending job and returns its answer, failure, or `request`. Repeat while `status` is `queued` or `running`. |
| `follow_up` | Continues a finished provider conversation. Returns the next answer or pending `job_id`. |
| `finish` | After you review a terminal result and changed files, acknowledges the job and removes only its owned disposable files. Requires `reviewed: true`. |
| `cancel` | Requests cancellation of a running job. Collect its terminal status before finishing. |
| `recommend` | Matches `quick`, `implementation`, `feature`, `architecture`, or `visual` work to the current provider catalog. Makes no model call. |
| `check` | Checks CLI availability and account status. Makes no model call. |
| `send` | Queues a message. An active provider turn receives it only on a later turn. |
| `thread_read` | Last messages of an Antigravity desktop-app thread the user named by id (`{"thread_id":"…","last":4}`). No model call. |
| `thread_ask` | Sends a message into that app thread and returns its answer (`{"thread_id":"…","prompt":"…","sender":"Claude"}`, plan mode by default). `status: no_answer` comes with a `hint`. Both turns are saved in the thread; tell the user to close and reopen it in the app if it is open, since the app does not refresh an open thread. |
| `permissions_status` | Compares Antigravity, Codex and Claude permission files with [the baseline policy](references/permission-policy.json). No model call, no arguments. |
| `permissions_apply` | Merges the policy into those files with backups. Needs `user_approved: true` (only after the user agreed) or `dry_run: true`. `tools` defaults to antigravity + codex. |
| `permissions_test` | Checks the rules without model calls; `live: true` runs each agent in a throwaway repo and checks that commits are blocked and network works. |

Call `python3 <skill>/scripts/agent_tools.py help` for the operation list. Pass named arguments as a JSON object in a task-owned file, then call `python3 <skill>/scripts/agent_tools.py OPERATION --json-file /path/to/args.json`. Keep prompts in that JSON file or use `prompt_file`; do not interpolate user text into a shell command. Remove the temporary argument file after the call.

For example, `run` takes `{"provider":"codex","cwd":"/absolute/project","prompt":"Review the change","task":"implementation","parent_id":"review-1","write_mode":false}`. Its JSON result contains `status`, `job_id`, and `answer` when finished. If `answer_truncated` is true, read `result_path`. For a longer run, use `collect` with `{"job_id":"..."}`. After reviewing the result, use `finish` with `{"job_id":"...","reviewed":true}`. For another turn, call `follow_up` before `finish` with `{"job_id":"...","prompt":"..."}`.

Honor an explicitly requested provider and model. `run` selects from the live catalog only when `task` is provided without `model`; otherwise the provider CLI uses its configured default. If selection fails, report it instead of silently changing provider or model. Antigravity can list partner models, so `agy` alone does not identify the model provider. For selection rationale or unusual tasks, read [model selection](references/model-selection.md); for provider failures, read [provider notes](references/providers.md). To talk to a thread the user started in the Antigravity desktop app, use `thread_read` then `thread_ask`.

To change what agents may do, edit the policy file and run `permissions_apply` then `permissions_test`; read [permissions](references/permissions.md) only if one of them fails. Default to read-only. Set `write_mode: true` only for already-authorized edits and give each job a concrete objective, working directory, allowed write scope, acceptance checks, and handoff location. Include the project's instructions and cleanup requirements. Provider login and permissions do not inherit the parent's app or OS approvals. Review the actual output and changed files before declaring success. A durable job event cannot wake an ended chat; keep collecting while required work remains.

Keep scratch in the job's owned directory when practical. `finish` only removes bridge-owned disposable files; preserve project work, deliverables, credentials, provider conversations, and uncertain paths. Never finish a live job. If a child needs input, handle its `request` within existing authorization and use `follow_up`.

If this interface misbehaves, reproduce the failure, make a focused fix, add a meaningful regression test, run the relevant tests and skill validator, and report the evidence. Preserve working APIs and in-flight jobs.
