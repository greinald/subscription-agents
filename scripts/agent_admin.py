"""Agent administration: Antigravity app threads and standing agent permissions.

Exposed through agent_tools.py as thread_read, thread_ask, permissions_status,
permissions_apply and permissions_test. The baseline policy is data in
references/permission-policy.json.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_PATH = os.path.join(SKILL_DIR, "references", "permission-policy.json")
THREAD_ID_RX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TOOLS = ("antigravity", "codex", "claude")


def _home(home):
    return os.path.abspath(os.path.expanduser(home or "~"))


def _paths(home):
    h = _home(home)
    return {
        "antigravity_cli": os.path.join(h, ".gemini", "antigravity-cli", "settings.json"),
        "antigravity_app": os.path.join(h, ".gemini", "config", "config.json"),
        "codex_rules": os.path.join(h, ".codex", "rules", "default.rules"),
        "codex_config": os.path.join(h, ".codex", "config.toml"),
        "claude": os.path.join(h, ".claude", "settings.json"),
        "agy": os.path.join(h, ".gemini", "bin", "agy"),
        "brain": os.path.join(h, ".gemini", "antigravity", "brain"),
    }


def _policy(home=None):
    with open(os.environ.get("AGENT_PERMISSION_POLICY", POLICY_PATH), encoding="utf-8") as f:
        policy = json.load(f)
    h = _home(home)
    policy["antigravity_allow"] = [rule.replace("(~/", f"({h}/") for rule in policy["antigravity_allow"]]
    return policy


def _agy_rule(words):
    return f"command({' '.join(words)})"


def _claude_rule(words):
    return f"Bash({' '.join(words)}:*)"


def _codex_rule(words):
    pattern = ", ".join(json.dumps(w) for w in words)
    return (f'prefix_rule(pattern = [{pattern}], decision = "forbidden", '
            f'justification = "Baseline deny list (subscription-agents permission-policy.json).")')


def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _codex_patterns(path):
    if not os.path.exists(path):
        return set()
    text = open(path, encoding="utf-8").read()
    found = set()
    for match in re.finditer(r"prefix_rule\(\s*pattern\s*=\s*\[([^\]]*)\][^)]*decision\s*=\s*\"forbidden\"", text):
        found.add(tuple(json.loads(f"[{match.group(1)}]")))
    return found


def _toml_top_value(text, key):
    top = text.split("\n[", 1)[0]
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", top, re.M)
    return match.group(1).strip() if match else None


def _toml_section_value(text, section, key):
    match = re.search(rf"^\[{re.escape(section)}\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not match:
        return None
    value = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", match.group(1), re.M)
    return value.group(1).strip() if value else None


def _codex_cli(codex_cli=None, home=None):
    if codex_cli:
        return codex_cli
    found = shutil.which("codex")
    if found:
        return found
    candidates = sorted(glob.glob(os.path.join(_home(home), ".nvm", "versions", "node", "*", "bin", "codex")))
    return candidates[-1] if candidates else None


def permissions_status(*, home=None):
    """Compare each tool's standing permission files with the baseline policy; no model call."""
    p, policy = _paths(home), _policy(home)
    deny = [tuple(w) for w in policy["deny_commands"]]
    out = {}

    cli = _load_json(p["antigravity_cli"])
    perms = (cli or {}).get("permissions", {})
    out["antigravity_cli"] = {
        "file": p["antigravity_cli"], "exists": cli is not None,
        "missing_deny": [_agy_rule(w) for w in deny if _agy_rule(w) not in perms.get("deny", [])],
        "missing_allow": [r for r in policy["antigravity_allow"] if r not in perms.get("allow", [])]}

    app = _load_json(p["antigravity_app"])
    grants = ((app or {}).get("userSettings") or {}).get("globalPermissionGrants") or {}
    out["antigravity_app"] = {
        "file": p["antigravity_app"], "exists": app is not None,
        "preset": ((app or {}).get("userSettings") or {}).get("permissionPreset"),
        "missing_deny": [_agy_rule(w) for w in deny if _agy_rule(w) not in grants.get("deny", [])]}

    rules = _codex_patterns(p["codex_rules"])
    text = open(p["codex_config"], encoding="utf-8").read() if os.path.exists(p["codex_config"]) else ""
    web = _toml_top_value(text, "web_search")
    net = _toml_section_value(text, "sandbox_workspace_write", "network_access")
    out["codex"] = {
        "rules_file": p["codex_rules"], "config_file": p["codex_config"],
        "missing_deny": [" ".join(w) for w in deny if w not in rules],
        "web_search": web, "network_access": net,
        "network_ok": web == json.dumps(policy["codex_web_search"]) and net == str(policy["codex_network_access"]).lower()}

    claude = _load_json(p["claude"])
    claude_deny = ((claude or {}).get("permissions") or {}).get("deny", [])
    out["claude"] = {"file": p["claude"], "exists": claude is not None,
                     "missing_deny": [_claude_rule(w) for w in deny if _claude_rule(w) not in claude_deny]}

    out["ok"] = {
        "antigravity": not out["antigravity_cli"]["missing_deny"] and not out["antigravity_cli"]["missing_allow"]
                       and (app is None or not out["antigravity_app"]["missing_deny"]),
        "codex": not out["codex"]["missing_deny"] and out["codex"]["network_ok"],
        "claude": not out["claude"]["missing_deny"]}
    return out


def _backup(path, stamp):
    if os.path.exists(path):
        target = f"{path}.bak-{stamp}"
        shutil.copy2(path, target)
        return target
    return None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    json.loads(text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _union(existing, extra):
    return list(existing) + [x for x in extra if x not in existing]


def permissions_apply(*, user_approved=False, tools=("antigravity", "codex"), dry_run=False, home=None):
    """Merge the baseline policy into each tool's files. Needs user_approved=true unless dry_run."""
    tools = [tools] if isinstance(tools, str) else list(tools)
    unknown = set(tools) - set(TOOLS)
    if unknown:
        raise ValueError(f"unknown tools {sorted(unknown)}; use {list(TOOLS)}")
    if not dry_run and user_approved is not True:
        raise ValueError("changing another agent's permissions needs the user's approval: pass user_approved=true "
                         "after the user agreed, or dry_run=true to preview")
    status = permissions_status(home=home)
    p, policy = _paths(home), _policy(home)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    changes = []

    def change(path, what, apply):
        changes.append({"file": path, "change": what})
        if not dry_run:
            backup = _backup(path, stamp)
            apply()
            changes[-1]["backup"] = backup

    if "antigravity" in tools:
        s = status["antigravity_cli"]
        if s["missing_deny"] or s["missing_allow"]:
            def apply_cli():
                data = _load_json(p["antigravity_cli"]) or {}
                perms = data.setdefault("permissions", {})
                perms["allow"] = _union(perms.get("allow", []), s["missing_allow"])
                perms["deny"] = _union(perms.get("deny", []), s["missing_deny"])
                _write_json(p["antigravity_cli"], data)
            change(p["antigravity_cli"], {"add_allow": s["missing_allow"], "add_deny": s["missing_deny"]}, apply_cli)
        a = status["antigravity_app"]
        if a["exists"] and a["missing_deny"]:
            def apply_app():
                data = _load_json(p["antigravity_app"])
                grants = data.setdefault("userSettings", {}).setdefault("globalPermissionGrants", {})
                grants["deny"] = _union(grants.get("deny", []), a["missing_deny"])
                _write_json(p["antigravity_app"], data)
            change(p["antigravity_app"], {"add_deny": a["missing_deny"]}, apply_app)

    if "codex" in tools:
        c = status["codex"]
        if c["missing_deny"]:
            missing = [w for w in map(tuple, policy["deny_commands"]) if " ".join(w) in c["missing_deny"]]
            def apply_rules():
                os.makedirs(os.path.dirname(p["codex_rules"]), exist_ok=True)
                existing = open(p["codex_rules"], encoding="utf-8").read() if os.path.exists(p["codex_rules"]) else ""
                lines = [_codex_rule(list(w)) for w in missing]
                with open(p["codex_rules"], "w", encoding="utf-8") as f:
                    f.write(existing.rstrip("\n") + ("\n" if existing else "") + "\n".join(lines) + "\n")
            change(p["codex_rules"], {"add_forbidden": c["missing_deny"]}, apply_rules)
        if not c["network_ok"]:
            def apply_config():
                text = open(p["codex_config"], encoding="utf-8").read() if os.path.exists(p["codex_config"]) else ""
                web_line = f"web_search = {json.dumps(policy['codex_web_search'])}"
                head, sep, rest = text.partition("\n[")
                if re.search(r"^web_search\s*=", head, re.M):
                    head = re.sub(r"^web_search\s*=.*$", web_line, head, flags=re.M)
                else:
                    head = head.rstrip("\n") + ("\n" if head else "") + web_line + "\n"
                text = head + sep + rest
                net_line = f"network_access = {str(policy['codex_network_access']).lower()}"
                section = re.search(r"^\[sandbox_workspace_write\]\s*$", text, re.M)
                if not section:
                    text = text.rstrip("\n") + f"\n\n[sandbox_workspace_write]\n{net_line}\n"
                elif _toml_section_value(text, "sandbox_workspace_write", "network_access") is None:
                    text = text[:section.end()] + f"\n{net_line}" + text[section.end():]
                else:
                    body = re.compile(r"(^\[sandbox_workspace_write\][^\n]*\n(?:(?!\[)[^\n]*\n)*?)network_access\s*=[^\n]*",
                                      re.M)
                    text = body.sub(lambda m: m.group(1) + net_line, text, count=1)
                os.makedirs(os.path.dirname(p["codex_config"]), exist_ok=True)
                with open(p["codex_config"], "w", encoding="utf-8") as f:
                    f.write(text)
            change(p["codex_config"], {"web_search": policy["codex_web_search"],
                                       "network_access": policy["codex_network_access"]}, apply_config)

    if "claude" in tools:
        cl = status["claude"]
        if cl["missing_deny"]:
            def apply_claude():
                data = _load_json(p["claude"]) or {}
                perms = data.setdefault("permissions", {})
                perms["deny"] = _union(perms.get("deny", []), cl["missing_deny"])
                _write_json(p["claude"], data)
            change(p["claude"], {"add_deny": cl["missing_deny"]}, apply_claude)

    return {"dry_run": bool(dry_run), "changes": changes,
            "status_after": None if dry_run else permissions_status(home=home)["ok"]}


def _codex_static_checks(policy, rules_file, codex):
    results = []
    for words in policy["deny_commands"]:
        command = list(words) + (["/tmp", "push"] if words[-1] in ("-C", "--git-dir", "--work-tree") else
                                 ["x=y", "commit"] if words[-1] == "-c" else ["x"])
        decision = _execpolicy(codex, rules_file, command)
        results.append({"command": " ".join(command), "expected": "forbidden", "got": decision,
                        "pass": decision == "forbidden"})
    decision = _execpolicy(codex, rules_file, ["git", "status"])
    results.append({"command": "git status", "expected": "not forbidden", "got": decision,
                    "pass": decision != "forbidden"})
    return results


def _execpolicy(codex, rules_file, command):
    proc = subprocess.run([codex, "execpolicy", "check", "--rules", rules_file, *command],
                          capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    try:
        return json.loads(proc.stdout).get("decision") or "no rule"
    except json.JSONDecodeError:
        return f"error: {proc.stderr.strip()[:200]}"


LIVE_PROMPT = (
    "Permission test in the current folder. Run each shell command separately, exactly as written, and do not "
    "try alternatives if one is blocked: 1) git status --short  2) git -C {repo} commit -m permission-test  "
    "3) curl -sS -o /dev/null -w '%{{http_code}}' https://example.com > net.txt  "
    "Then reply one line per command: the command, ALLOWED or BLOCKED, and its output.")


def _live_repo():
    root = tempfile.mkdtemp(prefix="agent-permission-test-")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    with open(os.path.join(repo, "a.txt"), "w") as f:
        f.write("test\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    return root, repo


def _live_verdict(repo, answer, commit_denied):
    has_commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo,
                                capture_output=True).returncode == 0
    net_file = os.path.join(repo, "net.txt")
    net = open(net_file).read().strip() if os.path.exists(net_file) else None
    return {"commit_expected": "blocked" if commit_denied else "allowed", "committed": has_commit,
            "network": net == "200", "curl_status": net,
            "pass": has_commit != commit_denied and net == "200", "answer": (answer or "")[:1500]}


def permissions_test(*, live=False, tools=("antigravity", "codex"), home=None, codex_cli=None, timeout_seconds=300):
    """Rule checks without model calls; live=true also runs each agent in a throwaway repo (uses tokens)."""
    tools = [tools] if isinstance(tools, str) else list(tools)
    p, policy = _paths(home), _policy(home)
    out = {"status": permissions_status(home=home)["ok"]}
    for name in ("antigravity_cli", "antigravity_app", "claude"):
        if os.path.exists(p[name]):
            try:
                _load_json(p[name])
            except json.JSONDecodeError as exc:
                out.setdefault("invalid_json", []).append(f"{p[name]}: {exc}")
    codex = _codex_cli(codex_cli, home)
    if "codex" in tools:
        if not codex:
            out["codex_static"] = "codex CLI not found"
        else:
            checks = _codex_static_checks(policy, p["codex_rules"], codex)
            out["codex_static"] = {"pass": all(c["pass"] for c in checks),
                                   "failures": [c for c in checks if not c["pass"]], "checked": len(checks)}
    if live:
        out["live"] = {}
        for tool in tools:
            if tool == "claude":
                out["live"]["claude"] = "live test not implemented; use permissions_status"
                continue
            root, repo = _live_repo()
            try:
                prompt = LIVE_PROMPT.format(repo=repo)
                if tool == "codex":
                    argv = [codex, "exec", "--skip-git-repo-check", "-C", repo, "-s", "workspace-write",
                            "-c", 'approval_policy="never"', "-c", 'model_reasoning_effort="low"', prompt]
                else:
                    argv = [p["agy"], "--output-format", "json", "--print-timeout", f"{timeout_seconds}s", "-p", prompt]
                try:
                    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True,
                                          timeout=timeout_seconds + 30, stdin=subprocess.DEVNULL)
                    answer = proc.stdout
                    if tool == "antigravity":
                        try:
                            answer = json.loads(proc.stdout).get("response") or proc.stdout
                        except json.JSONDecodeError:
                            pass
                except subprocess.TimeoutExpired:
                    answer = "timed out"
                out["live"][tool] = _live_verdict(repo, answer, ["git", "commit"] in policy["deny_commands"])
            finally:
                shutil.rmtree(root, ignore_errors=True)
    checks = [out.get("codex_static", {}).get("pass", True) if isinstance(out.get("codex_static"), dict) else False]
    checks += [v["pass"] for v in out.get("live", {}).values() if isinstance(v, dict)]
    out["pass"] = all(checks) and "invalid_json" not in out
    return out


def _thread_log(thread_id, home):
    if not THREAD_ID_RX.match(thread_id or ""):
        raise ValueError("thread_id must be an Antigravity conversation id like fd9a3bbf-0cd5-4249-a799-800b7e320bb3")
    path = os.path.join(_paths(home)["brain"], thread_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(path):
        raise ValueError(f"no Antigravity app thread {thread_id} (expected {path})")
    return path


def thread_read(thread_id, *, last=4, max_chars=4000, home=None):
    """Return the last user/agent messages of an Antigravity desktop-app thread; no model call."""
    messages = []
    with open(_thread_log(thread_id, home), encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("type") not in ("USER_INPUT", "PLANNER_RESPONSE") or not row.get("content"):
                continue
            text = row["content"]
            request = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", text, re.S)
            messages.append({"role": "user" if row["type"] == "USER_INPUT" else "agent",
                             "at": row.get("created_at"), "text": (request.group(1) if request else text)})
    picked = messages[-int(last):]
    for m in picked:
        if len(m["text"]) > max_chars:
            m["text"], m["truncated"] = m["text"][:max_chars], True
    return {"thread_id": thread_id, "messages": picked, "total_messages": len(messages)}


def thread_ask(thread_id, *, prompt=None, prompt_file=None, sender=None, mode="plan", model=None,
               timeout_seconds=900, home=None, agy_cli=None):
    """Send a message into an Antigravity desktop-app thread and return its answer."""
    _thread_log(thread_id, home)
    if prompt_file:
        with open(prompt_file, encoding="utf-8") as f:
            prompt = f.read()
    if not prompt:
        raise ValueError("pass prompt or prompt_file")
    if mode not in ("plan", "accept-edits", "auto"):
        raise ValueError("mode must be plan, accept-edits or auto")
    if sender:
        prompt = f"This is {sender}, writing in your thread at the user's request.\n\n{prompt}"
    argv = [agy_cli or _paths(home)["agy"], "--app_data_dir=antigravity", "--conversation", thread_id,
            "--mode", mode, "--output-format", "json", "-p", prompt]
    if model:
        argv[1:1] = ["--model", model]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_seconds,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"thread_ask timed out after {timeout_seconds}s; read the reply later with thread_read") from exc
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"response": None, "raw": proc.stdout[-2000:]}
    answer = data.get("response")
    denied = data.get("denied_actions") or []
    stderr = proc.stderr.strip()[-1000:]
    result = {"thread_id": thread_id, "status": "answered" if answer else "no_answer", "answer": answer,
              "denied_actions": denied, "exit_code": proc.returncode, "stderr": stderr or None}
    if not answer:
        result["hint"] = ("No answer. If stderr or denied_actions name a refused command, resume with the instruction "
                          "to use only read_file, or ask the user to extend the permission policy "
                          "(permissions_apply). 'trajectory not found' means the id is not an app thread.")
    return result
