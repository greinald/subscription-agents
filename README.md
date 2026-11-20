# Subscription Agents

A Codex skill and Python bridge for delegating work to Claude Code, Codex, and Google Antigravity through their installed CLIs and existing account sessions.

The bridge starts bounded background jobs, records completion events, supports follow-up turns and messages, and cleans up only files owned by each job. It uses Python's standard library.

## Install

Clone this repository into your agent skills directory as `subscription-agents`, or link the checkout there. Read [SKILL.md](SKILL.md) before use.

## Model selection

The `recommend` command matches a task type to models currently listed by the provider CLI. It does not call a model:

```bash
python3 scripts/agent_bridge.py recommend provider=codex task=implementation
```

Task types: `quick`, `implementation`, `feature`, `architecture`, and `visual`. Claude Code currently has no verified model-list command, so the bridge reports that limitation.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

See [the harness reference](references/harness.md) for the Python API and JSON CLI.
