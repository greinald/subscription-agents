# Subscription Agents

A Codex skill and Python bridge for delegating work to Claude Code, Codex, and Google Antigravity through their installed CLIs and existing account sessions.

The bridge starts bounded background jobs, records completion events, supports follow-up turns and messages, and cleans up only files owned by each job. It uses Python's standard library.

## Install

Clone this repository into your agent skills directory as `subscription-agents`, or link the checkout there. Read [SKILL.md](SKILL.md) before use.

## Model selection

The compact interface returns answers and job status as JSON. It lists its operations without reading Python source:

```bash
python3 scripts/agent_tools.py help
python3 scripts/agent_tools.py run --json-file /path/to/task-arguments.json
```

`run` can select from the current provider catalog when its JSON input includes a `task`: `quick`, `implementation`, `feature`, `architecture`, or `visual`. Claude Code currently has no verified model-list command, so the interface reports that limitation. Read [SKILL.md](SKILL.md) for the short operation guide.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The lower-level [harness reference](references/harness.md) covers advanced events, messages, and provider configuration.
