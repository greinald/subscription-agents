---
name: subscription-agents
description: Delegate tasks to Claude, Codex, or Gemini through installed account-authenticated CLIs, with callable job functions, shared messages, completion events, and owned-file cleanup. Use when coordinating another AI or managing external agent jobs.
---

# Subscription agents

Use the installed provider CLI and its existing account session. Use the requested provider and exact model; report authentication, version, or entitlement failures instead of silently switching models or API billing.

The reusable implementation is [scripts/agent_bridge.py](scripts/agent_bridge.py). Read [references/harness.md](references/harness.md) for its Python functions and JSON CLI, including model/effort selection, follow-up turns, event waits, cancellation, and cleanup. Read [references/providers.md](references/providers.md) when selecting or troubleshooting a provider.

For an unspecified model, call `recommend_model(provider, task)` (or the JSON CLI `recommend` command) with `quick`, `implementation`, `feature`, `architecture`, or `visual`. It checks the live account catalog and returns a model, matching effort, and alternatives without making a model request. Read [references/model-selection.md](references/model-selection.md) for the task mapping and limits. If the catalog is unavailable or no family matches, choose explicitly after verification; never silently substitute. Claude Code has no verified catalog command, so its recommendation reports that limitation. Prefer Google models when the user requests Gemini/Google through Antigravity; Antigravity also offers partner models, so the service name alone does not identify the model provider.

## Delegate and stay responsible

Give each job a concrete objective, working directory, allowed write scope, acceptance checks, and handoff location. Assign one writer per file area; researchers can work concurrently. Default to read-only. Delegate edits only within the user's existing authorization. Pass relevant project instructions and the cleanup requirements below to every child.

The parent decides each child's permitted work and passes the corresponding write mode, allowed tools, and MCP configuration through the functions. Native collaboration tools may inherit the parent's execution context; external provider processes have their own permission systems. Account login, OS administration, and an app's per-agent approval do not automatically transfer. See the Xcode note in [references/providers.md](references/providers.md) when an approved parent can use Xcode but its child cannot.

Start a job with a stable `parent_id`. Keep its ID and the last consumed event ID. Use the harness's bounded event wait while required children work; inspect completion/failure messages and continue the parent task without requiring the user to ask for status. Surface meaningful progress, then review the actual changed files, checks, and artifacts before declaring completion. A child saying “done” is a handoff, not proof of correctness.

Messages in the shared inbox are durable. During an active CLI turn, a message may be queued for the next turn; use the documented resume function to consume it. Do not claim live interruption unless the provider adapter actually supports it. Change model or effort on a new/resumed turn using the adapter's supported flags.

A child that cannot write the inbox can finish its turn with the structured request described in the harness reference. The worker records `needs_input`, places the request in the parent's inbox, and emits `job.needs_input`. The parent answers with `resume_agent`; a request for help is not task completion. This works across providers without granting a researcher project edit access.

A durable event is not by itself a notification to an ended chat. Keep the parent's event wait active until its required work is complete, or connect the optional completion callback to a real host wake mechanism. Do not promise unattended future chat messages without that integration.

## Cleanup is part of completing every job

- Put disposable prompts, logs, captures, downloads, and experiments in the job's owned scratch directory. Track ownership in its manifest and bound raw logs.
- After reviewing a finished or failed job, move requested deliverables to their intended destination, retain a concise handoff, then call the harness acknowledgement/cleanup operation. Do this before the parent finishes; do not leave cleanup as a suggestion for the next agent.
- Delete only owned disposable paths. Preserve repository work, final deliverables, user files, provider conversations/credentials, shared caches/dependencies, and files belonging to another job. Do not follow symlinks or sweep shared temporary folders.
- Do not clean a live job. Cancel only the harness-owned process group if cancellation is needed, wait for exit, then clean it. For interrupted/stale work, verify process identity and ownership first.
- If a path's value or ownership is unclear, preserve it and report its path and size. Report any cleanup failure or retained large intermediate explicitly.

Include those requirements in child prompts even though the harness implements ownership checks. The parent remains responsible for disposable files it created outside the harness.

## Improve this skill when usage reveals a problem

The user authorizes agents using this skill to repair demonstrated bugs in its instructions, provider adapters, communication, or cleanup functions. Reproduce the problem, make a focused correction in this shared skill folder, add a meaningful regression test when behavior changes, and run the relevant tests and skill validator. Fix misleading documentation when observed CLI behavior differs. Report what changed and the verification in the task handoff.

Coordinate one writer for the affected files. Preserve working APIs and in-flight jobs. Do not weaken cleanup ownership checks, widen permissions, switch billing routes, silently substitute models, or change unrelated global settings to make a test pass. If a repair needs authorization beyond the current task, report the concrete limitation. Remove repair scratch files after preserving the fix and evidence.
