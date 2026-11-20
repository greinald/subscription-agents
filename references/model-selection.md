# Model selection

Checked against official documentation on 2026-11-15. Keep an explicitly requested provider/model. For an unspecified choice, run `recommend_model(provider, task)` or the JSON CLI `recommend` command, then review its live-catalog result. Task names are `quick`, `implementation`, `feature`, `architecture`, and `visual`. This is a starting suggestion, not a permanent routing rule or a guarantee of model fit. Do not assume a benchmark proves visual taste.

## Google models through Antigravity

| Work | Starting choice | Reason |
|---|---|---|
| Defined coding changes, review fixes, quick UI iteration | Gemini 4 Hydrogen | Google explicitly positions Hydrogen for implementation and quick UI iteration. High is its default; XHigh adds reasoning depth. |
| Substantial feature work, refactoring or multi-file debugging | Orchestrator with the available planner | Google recommends Orchestrator for typical development: Carbon/Argon plans and reviews, Hydrogen implements, and control can return to the planner when needed. |
| Complex architecture, subtle concurrency, multi-repository migration | Available Carbon or Argon directly | Google recommends a standalone planner model when every step needs deeper reasoning. |
| Tiny connection checks or low-latency bounded work | A current Flash model | Local validation used Gemini 3.8 Flash for tiny checks. This is an operational choice, not a claim that Flash gives the best design result. |

Sources: [Google's model guide](https://antigravity.google/docs/models?hl=fi), [Hydrogen and Orchestrator announcement](https://antigravity.google/blog/gemini-4-hydrogen-in-google-antigravity/), [headless model selection](https://antigravity.google/docs/cli/headless/).

Run `list_models("agy")` or `agy models` for account-specific IDs. On this Mac the observed catalog included `gemini-4-hydrogen-xhigh`, Argon variants, Flash variants, and `gemini-pro-orchestrator-g1-pro`; Carbon was absent. Do not infer plan entitlement from the general documentation table or hardcode a catalog alias as permanent.

For a suffix-based ID, model and effort must match, e.g. `model="gemini-4-hydrogen-xhigh", effort="xhigh"`. Orchestrator uses a fixed configuration: start it without `effort`. The published model guide explains the planner options, while the local catalog supplies valid CLI IDs.

## Claude and Codex

Respect the user's exact requested model. Query local availability and current official guidance when choosing an unspecified model. A separate provider CLI can expose models not listed by this host's native subagent tool. Effort is an explicit per-turn option in the callable adapters. Provider-specific references and local verification are in [providers.md](providers.md) and [validation.md](validation.md).
