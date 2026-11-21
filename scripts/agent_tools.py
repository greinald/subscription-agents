#!/usr/bin/env python3
"""Small, self-describing interface to the subscription agent bridge.

Normal callers use these operations and their JSON results. The lower-level bridge
remains available for advanced event, message, and provider configuration.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import agent_admin as admin
import agent_bridge as bridge

MAX_WAIT_SECONDS = 55
DEFAULT_ANSWER_CHARS = 12000

OPERATIONS = {
    "run": {"purpose": "Start a provider turn; return its answer or a pending job_id.",
            "required": ["provider", "cwd", "prompt or prompt_file"],
            "optional": ["task", "model", "effort", "write_mode", "parent_id", "role",
                         "wait_seconds", "max_answer_chars", "run_root", "provider-specific bridge options"]},
    "collect": {"purpose": "Wait for one job; return its answer, failure, or input request.",
                "required": ["job_id"], "optional": ["wait_seconds", "max_answer_chars", "run_root"]},
    "follow_up": {"purpose": "Continue a finished conversation; return its next answer or pending job_id.",
                  "required": ["job_id"],
                  "optional": ["prompt", "model", "effort", "write_mode", "wait_seconds",
                               "max_answer_chars", "run_root"]},
    "finish": {"purpose": "After review, acknowledge and clean only bridge-owned disposable files.",
               "required": ["job_id", "reviewed=true"], "optional": ["note", "run_root"]},
    "cancel": {"purpose": "Request cancellation; collect terminal status before finish.",
               "required": ["job_id"], "optional": ["run_root"]},
    "recommend": {"purpose": "Choose an available model and matching effort; no model call.",
                  "required": ["provider", "task"], "optional": ["cli_override"]},
    "check": {"purpose": "Check CLI and account status; no model call.",
              "required": ["provider"], "optional": ["cli_override", "min_cli_version"]},
    "send": {"purpose": "Queue a message; active turns receive it only on a later turn.",
             "required": ["sender", "recipient", "body"], "optional": ["kind", "run_root"]},
    "thread_read": {"purpose": "Last messages of an Antigravity desktop-app thread; no model call.",
                    "required": ["thread_id"], "optional": ["last", "max_chars"]},
    "thread_ask": {"purpose": "Send a message into an Antigravity desktop-app thread; return its answer.",
                   "required": ["thread_id", "prompt or prompt_file"],
                   "optional": ["sender", "mode (plan|accept-edits|auto, default plan)", "model", "timeout_seconds"]},
    "permissions_status": {"purpose": "Compare agents' standing permissions with the baseline policy; no model call.",
                           "required": [], "optional": []},
    "permissions_apply": {"purpose": "Merge the baseline policy into agent config files (backs them up).",
                          "required": ["user_approved=true (or dry_run=true)"],
                          "optional": ["tools (antigravity, codex, claude; default antigravity+codex)", "dry_run"]},
    "permissions_test": {"purpose": "Check rules without model calls; live=true also runs each agent in a throwaway repo.",
                         "required": [], "optional": ["live", "tools", "timeout_seconds"]},
}


def _wait_seconds(value):
    value = float(value)
    if not 0 <= value <= MAX_WAIT_SECONDS:
        raise ValueError(f"wait_seconds must be 0..{MAX_WAIT_SECONDS}")
    return value


def _answer_chars(value):
    value = int(value)
    if not 1 <= value <= 256 * 1024:
        raise ValueError("max_answer_chars must be 1..262144")
    return value


def _view(b, job_id, max_answer_chars):
    status = b.get_status(job_id)
    out = {"job_id": job_id, "status": status["status"], "terminal": status["terminal"],
           "provider": status["provider"], "model": status["model"],
           "failure_reason": status["failure_reason"], "answer": None,
           "request": None, "artifacts": status["artifacts"]}
    if status["terminal"]:
        result = b.get_result(job_id, max_chars=max_answer_chars + 1)
        answer = result.get("result_text") or ""
        out["answer"] = answer[:max_answer_chars] or None
        out["answer_truncated"] = len(answer) > max_answer_chars
        out["result_path"] = result.get("result_path")
        summary = result.get("summary") or {}
        out["request"] = summary.get("request")
        out["model_reported"] = summary.get("model_reported")
        out["warnings"] = summary.get("warnings") or []
    return out


def collect(job_id, *, wait_seconds=MAX_WAIT_SECONDS, max_answer_chars=DEFAULT_ANSWER_CHARS,
            run_root=None):
    """Wait up to 55 seconds for one job; return a compact result without cleaning it."""
    wait_seconds = _wait_seconds(wait_seconds)
    max_answer_chars = _answer_chars(max_answer_chars)
    b = bridge.Bridge(run_root)
    deadline = time.monotonic() + wait_seconds
    while True:
        out = _view(b, job_id, max_answer_chars)
        if out["terminal"] or time.monotonic() >= deadline:
            return out
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def run(provider, *, cwd, prompt=None, prompt_file=None, task=None, model=None, effort=None,
        wait_seconds=MAX_WAIT_SECONDS, max_answer_chars=DEFAULT_ANSWER_CHARS, run_root=None, **options):
    """Start a turn and return the answer when short enough to finish during this call."""
    if task and model is None:
        choice = bridge.recommend_model(provider, task, options.get("cli_override"))
        if not choice.get("ok"):
            return {"status": "model_selection_failed", "reason": choice.get("reason"),
                    "catalog": choice.get("catalog")}
        if effort is not None and choice["effort"] is not None and effort != choice["effort"]:
            raise ValueError("requested effort conflicts with the recommended model; specify an exact model")
        model, effort = choice["model"], effort if effort is not None else choice["effort"]
    b = bridge.Bridge(run_root)
    started = b.start_agent(provider, prompt, prompt_file=prompt_file, cwd=cwd,
                            model=model, effort=effort, **options)
    return collect(started["job_id"], wait_seconds=wait_seconds,
                   max_answer_chars=max_answer_chars, run_root=run_root)


def follow_up(job_id, *, prompt=None, wait_seconds=MAX_WAIT_SECONDS,
              max_answer_chars=DEFAULT_ANSWER_CHARS, run_root=None, **options):
    """Resume a finished conversation and return its next answer or pending job id."""
    b = bridge.Bridge(run_root)
    started = b.resume_agent(job_id, prompt, **options)
    return collect(started["job_id"], wait_seconds=wait_seconds,
                   max_answer_chars=max_answer_chars, run_root=run_root)


def finish(job_id, *, reviewed=False, note=None, run_root=None):
    """Clean bridge-owned disposable files only after the caller confirms review."""
    if reviewed is not True:
        raise ValueError("set reviewed=true only after reviewing the result and changed files")
    b = bridge.Bridge(run_root)
    acknowledgment = b.acknowledge(job_id, note)
    cleanup = b.cleanup_run(job_id)
    return {"job_id": job_id, "acknowledgment": acknowledgment, "cleanup": cleanup}


def cancel(job_id, *, run_root=None):
    """Cancel a running job without deleting its result or files."""
    return bridge.cancel_agent(job_id, run_root=run_root)


def recommend(provider, task, *, cli_override=None):
    """Return a model suggestion grounded in the live account catalog."""
    return bridge.recommend_model(provider, task, cli_override)


def check(provider, *, cli_override=None, min_cli_version=None):
    """Return CLI and account status without making a model request."""
    return bridge.check_provider(provider, cli_override, min_cli_version)


def send(sender, recipient, body, *, kind="note", run_root=None):
    """Queue a message; it does not interrupt an active model turn."""
    return bridge.send_message(sender, recipient, body, kind, run_root=run_root)


CALLS = {"run": run, "collect": collect, "follow_up": follow_up, "finish": finish,
         "cancel": cancel, "recommend": recommend, "check": check, "send": send,
         "thread_read": admin.thread_read, "thread_ask": admin.thread_ask,
         "permissions_status": admin.permissions_status, "permissions_apply": admin.permissions_apply,
         "permissions_test": admin.permissions_test}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("operation", choices=["help", *CALLS])
    parser.add_argument("--json-file", help="JSON object with the operation's named arguments")
    args = parser.parse_args(argv)
    try:
        if args.operation == "help":
            result = OPERATIONS
        else:
            if not args.json_file and args.operation not in ("permissions_status", "permissions_test"):
                raise ValueError("pass --json-file with an object of named arguments")
            params = {}
            if args.json_file:
                with open(args.json_file, encoding="utf-8") as f:
                    params = json.load(f)
            if not isinstance(params, dict):
                raise ValueError("JSON input must be an object")
            result = CALLS[args.operation](**params)
        print(json.dumps({"ok": True, "result": result}, sort_keys=True, default=str))
        return 0
    except (OSError, TypeError, ValueError, KeyError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
