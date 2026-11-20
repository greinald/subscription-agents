# Validation on this Mac — 2026-11-15

## Automated behavior checks

`python3 -m unittest discover -s tests -v`: **25 tests passed**, Python 3.14.6, 14.755 seconds. Tests use fake CLIs and no network. They cover background completion, shared messages, read-only request/answer/resume, model and effort flags, zero-exit provider errors, cancellation ownership, capped output, external transcript watching, cleanup preserving artifacts/symlinks/unrelated files, and restricted process inspection.

The skill-creator `quick_validate.py` also passed. Its PyYAML dependency was installed only in a disposable validation environment; the harness itself uses Python's standard library.

## Real provider checks

| Provider | New turn | Follow-up turn | Account route |
|---|---|---|---|
| Claude Code 2.1.325 | `claude-opus-5-5`, low effort: `HARNESS_OK` | Same session, medium effort: `RESUME_OK` | Claude account; Pro verified by supported auth status |
| Codex 0.169.0 | `gpt-6-sol`, low effort: `HARNESS_OK` | Same session, medium effort: `RESUME_OK` | ChatGPT login verified |
| Antigravity 1.5.9 | `gemini-3.8-flash-low`, low effort: `HARNESS_OK` | Same conversation, explicitly selected `gemini-3.8-flash-medium`: `RESUME_OK` | Existing Google session; exact subscription tier unverified |

All succeeded through `start_agent`/`resume_agent`, with durable terminal events and recorded session IDs. API-key environment variables were removed from children. Codex and Antigravity do not report an independently confirmed actual model in their result streams; the requested model and exact argv are recorded.

A real conflicting Antigravity model suffix/effort pair failed clearly. The adapter now rejects this before launch. A reader inside a restrictive sandbox also exposed a false stale-job detection bug; that was fixed with conservative liveness checks and regression tests, and the still-running builder's state was repaired after positive process identity checks.

## Communication in actual work

A Claude Opus 5.5 product-detail builder ran through the harness and sent its parent a structured `render_request` with the requested previews and sizes. The message appeared in the parent inbox and event channel. Strict read-only request handoffs are additionally covered by the automated request → parent inbox → resume/answer test.

## Installed tool and limits

The working Claude native executable is retained at `~/.local/bin/claude` (about 331 MiB). The old global executable is preserved and rejected by the harness's minimum-version check; discovery falls back to the current user executable. This maintained tool is needed for future jobs and is not disposable run output.

Messages do not automatically inject into a running model. A completed host chat needs a real wake adapter; SQLite events alone cannot wake it. The parent must keep waiting while required work remains. Xcode's signed-agent approval is separate from provider permissions and may require a Mac administrator password. See the provider and harness references for those boundaries.

During real Antigravity builder use, exit-zero SUCCESS with denied_actions was discovered. The parser now rejects it; a regression test passes. Session-only permission allow rules and model-selection guidance were added from official Google documentation.

Real work also verified the provider-independent needs_input path: Google Gemini through Antigravity requested renders in final JSON, the worker wrote the parent inbox and emitted job.needs_input, and the parent resumed the same conversation with the rendered image paths. Canonical macOS screenshot paths were required by scoped file rules.

The cleaned PocketPot exercise handoffs are archived at `~/.local/state/agent-bridge/pocketpot-20261115` (use as `run_root`). Final Google review job: `job-20261115T174336Z-a2120fe0`. Raw prompts/logs/scratch were removed; result reports, manifests and durable events/messages remain. Production source and screenshots are in the project, outside run cleanup.
