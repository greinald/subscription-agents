"""Behavioural tests for scripts/agent_bridge.py using tiny fake provider executables.

No real model calls, no network, stdlib only. Run:
    python3 -m unittest discover -s tests -v      (from the subscription-agents directory)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import agent_bridge as ab  # noqa: E402

FAKE_TEMPLATE = r'''#!{python}
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sc = json.load(open(os.path.join(HERE, "{name}.scenario.json")))
argv = sys.argv[1:]
if argv == ["--version"]:
    print(sc.get("version", "9.9.9"))
    sys.exit(sc.get("version_exit", 0))
data = sys.stdin.read() if not sys.stdin.isatty() else ""
os.makedirs(os.path.join(HERE, "calls"), exist_ok=True)
rec = {{"argv": argv, "stdin": data, "cwd": os.getcwd(), "pid": os.getpid(), "tmpdir": os.environ.get("TMPDIR"),
       "env_keys": sorted(k for k in os.environ if "API_KEY" in k or k.startswith("AGENT_BRIDGE"))}}
with open(os.path.join(HERE, "calls", "%d-%d.json" % (time.time_ns(), os.getpid())), "w") as f:
    json.dump(rec, f)
model = argv[argv.index("--model") + 1] if "--model" in argv else (argv[argv.index("-m") + 1] if "-m" in argv else "")
time.sleep(sc.get("sleep", 0))
if sc.get("spam_bytes"):
    line = ("x" * 1023 + "\n")
    for _ in range(sc["spam_bytes"] // 1024):
        sys.stdout.write(line)
for ln in sc.get("stdout_lines", []):
    print(ln.replace("{{MODEL}}", model), flush=True)
if sc.get("stdout_raw"):
    sys.stdout.write(sc["stdout_raw"]); sys.stdout.flush()
if sc.get("last_message") is not None and "-o" in argv:
    with open(argv[argv.index("-o") + 1], "w") as f:
        f.write(sc["last_message"])
sys.stderr.write(sc.get("stderr", ""))
sys.exit(sc.get("exit", 0))
'''

CLAUDE_OK = [
    '{"type":"system","subtype":"init","session_id":"sess-1","model":"{MODEL}"}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}',
    '{"type":"result","subtype":"success","is_error":false,"result":"DONE","session_id":"sess-1",'
    '"num_turns":1,"modelUsage":{"{MODEL}":{}}}',
]


class ModelRecommendationTests(unittest.TestCase):
    def test_uses_live_agnostic_catalog_and_matching_effort(self):
        catalog = {"ok": True, "raw": "gemini-4-hydrogen-high\tHydrogen\n"
                   "gemini-3.8-flash-low\tFlash\nclaude-opus-5-5-high\tOpus\n"}
        with mock.patch.object(ab, "list_models", return_value=catalog):
            self.assertEqual(ab.recommend_model("agy", "implementation")["model"],
                             "gemini-4-hydrogen-high")
            self.assertEqual(ab.recommend_model("agy", "quick")["effort"], "low")

    def test_codex_picks_latest_visible_matching_family(self):
        catalog = {"ok": True, "models": [
            {"slug": "gpt-6.1-sol", "visibility": "list"},
            {"slug": "gpt-6.2-sol", "visibility": "list"},
            {"slug": "gpt-7-sol", "visibility": "hide"},
            {"slug": "gpt-6-astra", "visibility": "list"}]}
        with mock.patch.object(ab, "list_models", return_value=catalog):
            self.assertEqual(ab.recommend_model("codex", "implementation")["model"], "gpt-6.2-sol")
            self.assertEqual(ab.recommend_model("codex", "architecture")["model"], "gpt-6-astra")

    def test_no_silent_fallback_when_catalog_fails_or_family_missing(self):
        with mock.patch.object(ab, "list_models", return_value={"ok": False}):
            self.assertFalse(ab.recommend_model("agy", "quick")["ok"])
        with mock.patch.object(ab, "list_models", return_value={"ok": True, "models": []}):
            self.assertFalse(ab.recommend_model("codex", "visual")["ok"])
        self.assertFalse(ab.recommend_model("claude", "feature")["ok"])


class ProcessVisibilityTests(unittest.TestCase):
    def test_denied_process_inspection_does_not_mark_a_running_job_dead(self):
        bridge = object.__new__(ab.Bridge)
        row = {"status": "running", "worker_pid": 42, "worker_ident": "recorded start",
               "child_pid": 43, "child_ident": "child start", "job_id": "unused"}
        with mock.patch.object(ab, "_proc_ident", return_value=None), \
             mock.patch.object(ab, "_pid_alive", return_value=True), \
             mock.patch.object(bridge, "_finalize") as finalize:
            bridge._detect_stale(row)
            finalize.assert_not_called()
            self.assertFalse(ab._same_process(42, "recorded start"), "unknown identity must not authorize a kill")

    def test_terminal_status_cannot_enable_cleanup_of_a_live_provider(self):
        bridge = object.__new__(ab.Bridge)
        row = {"status": "failed", "kind": "agent", "child_pid": 42, "child_ident": "recorded start"}
        with mock.patch.object(bridge, "_row", return_value=row), \
             mock.patch.object(ab, "_proc_ident", return_value=None), \
             mock.patch.object(ab, "_pid_alive", return_value=True), \
             mock.patch.object(ab, "_cleanup_dir") as cleanup:
            self.assertFalse(bridge.cleanup_run("unused")["ok"])
            cleanup.assert_not_called()


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="agent-bridge-test-"))
        self.root = os.path.join(self.tmp, "state")
        self.fakes = os.path.join(self.tmp, "fakes")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.fakes)
        os.makedirs(self.project)
        self.b = ab.Bridge(self.root)
        self.cursor = {}
        self.event_buffer = {}
        self._procs = []

    def tearDown(self):
        for j in self.b.list_runs():
            if j["status"] in ab.ACTIVE:
                self.b.cancel_agent(j["job_id"], grace_seconds=1)
        for p in self._procs:
            if p.poll() is None:
                p.kill()
                p.wait()
        shutil.rmtree(self.tmp)

    # -- helpers
    def fake(self, name, scenario):
        path = os.path.join(self.fakes, name)
        with open(os.path.join(self.fakes, name + ".scenario.json"), "w") as f:
            json.dump(scenario, f)
        with open(path, "w") as f:
            f.write(FAKE_TEMPLATE.format(python=sys.executable, name=name))
        os.chmod(path, 0o755)
        return path

    def calls(self):
        d = os.path.join(self.fakes, "calls")
        if not os.path.isdir(d):
            return []
        out = []
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n)) as f:
                out.append(json.load(f))
        return out

    def await_event(self, job_id, types, channel="parent", timeout=40):
        """Block on wait_for_event (the harness's push-style API) until job_id emits one of types."""
        deadline = time.time() + timeout
        pending = self.event_buffer.setdefault(channel, [])
        while True:
            for index, ev in enumerate(pending):
                if ev["job_id"] == job_id and ev["type"] in types:
                    return pending.pop(index)
            if time.time() >= deadline:
                self.fail(f"no {types} event for {job_id} within {timeout}s")
            res = self.b.wait_for_event(channel, self.cursor.get(channel, 0), timeout=min(10, deadline - time.time()))
            self.cursor[channel] = res["cursor"]
            pending.extend(res["events"])

    def start(self, provider, prompt="do the thing", **kw):
        kw.setdefault("cwd", self.project)
        return self.b.start_agent(provider, prompt, **kw)


class LifecycleTests(BridgeTestCase):
    def test_agy_success_with_denied_actions_is_failure(self):
        cli = self.fake("agy", {"stdout_raw": json.dumps({"conversation_id": "conv-denied",
            "status": "SUCCESS", "response": "", "denied_actions": [{"action": "read_file"}]})})
        jid = self.start("agy", cli_override=cli)["job_id"]
        ev = self.await_event(jid, {"job.completed", "job.failed"})
        self.assertEqual(ev["type"], "job.failed")
        self.assertIn("permission denied", ev["payload"]["failure_reason"])
        self.assertEqual(ev["payload"]["session_id"], "conv-denied")

    def test_conflicting_agy_model_effort_is_rejected_without_starting_a_job(self):
        with self.assertRaisesRegex(ValueError, "different effort"):
            self.b.start_agent("agy", "Test", cwd=self.project,
                               model="gemini-3.8-flash-low", effort="medium")
        self.assertEqual(self.b.list_runs(), [])

    def test_start_returns_immediately_and_completion_arrives_as_event(self):
        cli = self.fake("claude", {"version": "2.1.325", "sleep": 1.5, "stdout_lines": CLAUDE_OK})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-should-not-reach-child"}):
            t0 = time.time()
            job = self.start("claude", "hello prompt", model="claude-test-model", effort="high",
                             cli_override=cli, role="researcher")
            launch = time.time() - t0
        self.assertLess(launch, 1.5, "start_agent must not wait for the provider run")
        self.assertFalse(self.b.get_status(job["job_id"])["terminal"])
        self.assertEqual(os.environ.get("ANTHROPIC_API_KEY"), None)  # parent env restored/untouched

        ev = self.await_event(job["job_id"], {"job.completed", "job.failed"})
        p = ev["payload"]
        self.assertEqual(ev["type"], "job.completed", p.get("failure_reason"))
        self.assertEqual(p["session_id"], "sess-1")
        self.assertEqual(p["model_requested"], "claude-test-model")
        self.assertEqual(p["model_reported"], "claude-test-model")
        self.assertEqual(p["effort"], "high")
        with open(p["result_path"]) as f:
            self.assertEqual(f.read(), "DONE")
        summary = self.b.get_result(job["job_id"])["summary"]
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(summary["env_removed"], ["ANTHROPIC_API_KEY"])

        (call,) = [c for c in self.calls()]
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-test-model")
        self.assertEqual(argv[argv.index("--effort") + 1], "high")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
        self.assertEqual(argv[-1], "--")
        self.assertNotIn("hello prompt", argv)
        self.assertTrue(call["stdin"].startswith("hello prompt\n"))
        self.assertNotIn("ANTHROPIC_API_KEY", call["env_keys"])
        self.assertIn("AGENT_BRIDGE_JOB_ID", call["env_keys"])
        self.assertTrue(call["tmpdir"].startswith(job["run_dir"]))
        self.assertEqual(call["cwd"], self.project)

    def test_provider_error_flags_fail_even_with_exit_zero(self):
        scenarios = {
            "claude": {"version": "2.1.325", "stdout_lines": [
                '{"type":"result","subtype":"error_during_execution","is_error":true,"result":"boom",'
                '"session_id":"s-err"}']},
            "codex": {"stdout_lines": ['{"type":"thread.started","thread_id":"t-err"}',
                                       '{"type":"turn.failed","error":{"message":"model metadata error"}}']},
            "agy": {"stdout_lines": ['{"conversation_id":"c-err","status":"ERROR","response":"","error":"quota"}']},
        }
        jobs = {prov: self.start(prov, cli_override=self.fake(prov, sc), model="m-1")["job_id"]
                for prov, sc in scenarios.items()}
        for prov, jid in jobs.items():
            with self.subTest(provider=prov):
                ev = self.await_event(jid, {"job.completed", "job.failed"})
                self.assertEqual(ev["type"], "job.failed")
                self.assertEqual(ev["payload"]["exit_code"], 0)
                self.assertTrue(ev["payload"]["failure_reason"])
        self.assertIn("model metadata error", self.b.get_status(jobs["codex"])["failure_reason"])
        self.assertIn("ERROR", self.b.get_status(jobs["agy"])["failure_reason"])
        self.assertEqual(self.b.get_status(jobs["codex"])["session_id"], "t-err")

    def test_codex_and_agy_success_parsing(self):
        codex = self.fake("codex", {"stdout_lines": [
            '{"type":"thread.started","thread_id":"thr-9"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"from-stream"}}',
            '{"type":"turn.completed","usage":{"input_tokens":3}}'], "last_message": "from-o-file"})
        agy = self.fake("agy", {"stdout_raw": json.dumps(
            {"conversation_id": "conv-7", "status": "SUCCESS", "response": "CONNECTION_OK\n"}, indent=2)})
        cj = self.start("codex", cli_override=codex, model="gpt-x", effort="medium")["job_id"]
        aj = self.start("agy", cli_override=agy, model="gemini-x", effort="low")["job_id"]
        ce = self.await_event(cj, {"job.completed", "job.failed"})
        ae = self.await_event(aj, {"job.completed", "job.failed"})
        self.assertEqual((ce["type"], ce["payload"]["session_id"]), ("job.completed", "thr-9"))
        self.assertEqual(self.b.get_result(cj)["result_text"], "from-o-file")
        self.assertEqual((ae["type"], ae["payload"]["session_id"]), ("job.completed", "conv-7"))
        self.assertEqual(self.b.get_result(aj)["result_text"], "CONNECTION_OK\n")

    def test_cancel_stops_only_the_jobs_own_process_group(self):
        cli = self.fake("claude", {"version": "2.1.325", "sleep": 60, "stdout_lines": CLAUDE_OK})
        bystander = subprocess.Popen(["sleep", "60"])
        bystander_session = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self._procs += [bystander, bystander_session]
        job = self.start("claude", cli_override=cli, model="m")
        started = self.await_event(job["job_id"], {"job.started"})
        child_pid = started["payload"]["pid"]
        res = self.b.cancel_agent(job["job_id"])
        self.assertTrue(res["cancelled"], res)
        ev = self.await_event(job["job_id"], {"job.cancelled", "job.failed", "job.completed"})
        self.assertEqual(ev["type"], "job.cancelled")
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
        self.assertIsNone(bystander.poll())
        self.assertIsNone(bystander_session.poll())
        again = self.b.cancel_agent(job["job_id"])
        self.assertFalse(again["cancelled"])

    def test_old_claude_cli_is_reported_not_substituted(self):
        cli = self.fake("claude", {"version": "2.0.8 (Claude Code)", "stdout_lines": CLAUDE_OK})
        job = self.start("claude", cli_override=cli, model="claude-opus-5-5")
        ev = self.await_event(job["job_id"], {"job.completed", "job.failed"})
        self.assertEqual(ev["type"], "job.failed")
        self.assertIn("too old", ev["payload"]["failure_reason"])
        self.assertIn("update", ev["payload"]["failure_reason"].lower())
        self.assertEqual(self.calls(), [], "provider must not be run with a too-old CLI")

    def test_raw_output_is_capped_but_final_result_kept(self):
        cap = 64 * 1024
        cli = self.fake("claude", {"version": "2.1.325", "spam_bytes": 3 * 1024 * 1024, "stdout_lines": CLAUDE_OK})
        job = self.start("claude", cli_override=cli, model="m", max_log_bytes=cap)
        ev = self.await_event(job["job_id"], {"job.completed", "job.failed"})
        self.assertEqual(ev["type"], "job.completed", ev["payload"]["failure_reason"])
        rd = job["run_dir"]
        on_disk = sum(os.path.getsize(os.path.join(rd, n)) for n in ("stdout.log", "stdout.log.1")
                      if os.path.exists(os.path.join(rd, n)))
        self.assertLessEqual(on_disk, 2 * cap)
        logs = self.b.get_result(job["job_id"])["summary"]["logs"]["stdout"]
        self.assertGreater(logs["bytes_seen"], 3 * 1024 * 1024)

    def test_callback_argv_receives_terminal_event_json(self):
        out = os.path.join(self.tmp, "callback-out.json")
        cb = os.path.join(self.fakes, "wake")
        with open(cb, "w") as f:
            f.write(f"#!{sys.executable}\nimport sys\nopen({out!r}, 'w').write(sys.stdin.read())\n")
        os.chmod(cb, 0o755)
        cli = self.fake("claude", {"version": "2.1.325", "stdout_lines": CLAUDE_OK})
        job = self.start("claude", cli_override=cli, model="m", callback_argv=[cb])
        ev = self.await_event(job["job_id"], {"callback.done"})
        self.assertEqual(ev["payload"]["exit_code"], 0)
        with open(out) as f:
            payload = json.load(f)
        self.assertEqual((payload["job_id"], payload["status"]), (job["job_id"], "completed"))


class MessagingTests(BridgeTestCase):
    def test_read_only_child_request_notifies_parent_and_can_resume(self):
        request = ab.make_input_request("Please render the phone details preview", "render_request")
        result = {"type": "result", "subtype": "success", "is_error": False,
                  "result": request, "session_id": "sess-1"}
        cli = self.fake("claude", {"version": "2.1.325", "stdout_lines": [json.dumps(result)]})
        job = self.start("claude", "Research read-only", cli_override=cli)
        ev = self.await_event(job["job_id"], ["job.needs_input"])
        self.assertEqual(ev["payload"]["status"], "needs_input")
        self.assertEqual(self.b.read_messages("parent")[0]["kind"], "render_request")
        self.assertFalse(self.b.get_status(job["job_id"])["write_mode"])
        self.b.send_message("parent", job["job_id"], "Preview is ready at /review/phone.png")
        self.fake("claude", {"version": "2.1.325", "stdout_lines": CLAUDE_OK})
        resumed = self.b.resume_agent(job["job_id"], "Continue with the supplied preview")
        self.await_event(resumed["job_id"], ["job.completed"])
        self.assertIn("/review/phone.png", self.calls()[-1]["stdin"])

    def test_messages_queue_during_turn_and_resume_delivers_them_with_new_model(self):
        cli = self.fake("claude", {"version": "2.1.325", "sleep": 1.5, "stdout_lines": CLAUDE_OK})
        a = self.start("claude", "first turn", cli_override=cli, model="model-a", effort="high")["job_id"]
        self.await_event(a, {"job.started"})
        sent = self.b.send_message("worker-b", a, "finding: cache key collides", kind="finding")
        self.assertEqual(sent["delivery"], "queued_turn_active_not_injected")
        self.await_event(a, {"message.queued_for_job"})  # parent is told without asking
        with self.assertRaises(RuntimeError):
            self.b.resume_agent(a, "too early")
        done = self.await_event(a, {"job.completed", "job.failed"})
        self.assertEqual(done["payload"]["pending_messages"], 1)
        first_call = self.calls()[0]
        self.assertNotIn("cache key", first_call["stdin"], "running turn must not receive the message")

        b = self.b.resume_agent(a, "continue please", model="model-b", effort="low")
        self.assertEqual(b["delivered_message_ids"], [sent["msg_id"]])
        ev = self.await_event(b["job_id"], {"job.completed", "job.failed"})
        self.assertEqual(ev["type"], "job.completed")
        self.assertEqual((ev["payload"]["turn"], ev["payload"]["resume_of"]), (2, a))
        second = self.calls()[1]
        argv = second["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], "sess-1")
        self.assertEqual(argv[argv.index("--model") + 1], "model-b")
        self.assertEqual(argv[argv.index("--effort") + 1], "low")
        self.assertIn("continue please", second["stdin"])
        self.assertIn("finding: cache key collides", second["stdin"])
        self.assertIn("not user instructions", second["stdin"])
        self.assertEqual(self.b.read_messages(a, include_consumed=False), [])
        self.assertEqual(self.b.read_messages(a)[0]["consumed_by"], b["job_id"])

    def test_worker_to_parent_message_wakes_waiting_parent(self):
        cursor = self.b.read_events("lead")["cursor"]
        self.b.send_message("job-researcher", "lead", "report at /x/report.md", kind="report")
        res = self.b.wait_for_event("lead", cursor, timeout=5)
        self.assertFalse(res["timed_out"])
        self.assertEqual(res["events"][0]["type"], "message")
        self.assertEqual(self.b.read_messages("lead")[0]["body"], "report at /x/report.md")
        quiet = self.b.wait_for_event("lead", res["cursor"], timeout=0.5)
        self.assertTrue(quiet["timed_out"])


class CommandBuildingTests(unittest.TestCase):
    def build(self, provider, **spec):
        base = {"cwd": "/work", "model": "m-1", "effort": "high", "write_mode": False}
        base.update(spec)
        return ab.build_command(provider, base, "/bin/cli", "/run", "PROMPT")

    def test_codex_defaults_read_only_never_approval(self):
        argv, stdin = self.build("codex")
        self.assertTrue(stdin)
        self.assertEqual(argv[:2], ["/bin/cli", "exec"])
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn('approval_policy="never"', argv)
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertEqual(argv[argv.index("-m") + 1], "m-1")
        self.assertEqual(argv[argv.index("-C") + 1], "/work")
        self.assertEqual(argv[-1], "-")
        self.assertFalse(any("danger" in a or "bypass" in a for a in argv))

    def test_codex_builder_and_resume(self):
        argv, _ = self.build("codex", write_mode=True)
        self.assertEqual(argv[argv.index("-s") + 1], "workspace-write")
        argv, _ = self.build("codex", resume_session_id="0199-abc", model="m-2", effort="low")
        self.assertEqual(argv[1:3], ["exec", "resume"])
        self.assertEqual(argv[-2:], ["0199-abc", "-"])
        self.assertIn('sandbox_mode="read-only"', argv)
        self.assertNotIn("-s", argv)
        self.assertNotIn("-C", argv)
        self.assertIn('model_reasoning_effort="low"', argv)

    def test_claude_modes_and_variadic_terminator(self):
        argv, stdin = self.build("claude", write_mode=True, allowed_tools=["Read", "Edit"],
                                 mcp_config='{"mcpServers":{}}', agents='{"r":{}}')
        self.assertTrue(stdin)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(argv[-3:], ["Read", "Edit", "--"])
        self.assertFalse(any("bypass" in a.lower() or "dangerously" in a for a in argv))
        argv, _ = self.build("claude")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")

    def test_agy_modes_resume_and_flag_like_prompt(self):
        argv, stdin = self.build("agy")
        self.assertFalse(stdin)
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")
        self.assertEqual(argv[-2:], ["-p", "PROMPT"])
        argv, _ = self.build("agy", write_mode=True, resume_session_id="conv-1")
        self.assertEqual(argv[argv.index("--mode") + 1], "accept-edits")
        self.assertEqual(argv[argv.index("--conversation") + 1], "conv-1")
        argv, _ = ab.build_command("agy", {"cwd": "/w"}, "/bin/agy", "/run", "--help me")
        self.assertFalse(argv[-1].startswith("-"))

    def test_agy_settings_make_path_rules_work(self):
        # agy rejects glob path rules (read_file(/dir/**) was denied, read_file(/dir) allowed:
        # verified live 2026-11-22), so globs become directories, macOS /tmp aliases are added,
        # and the job cwd is always readable even without caller settings.
        argv, _ = self.build("agy")
        allow = json.loads(argv[argv.index("--settings") + 1])["permissions"]["allow"]
        self.assertEqual(allow, ["read_file(/work)"])
        settings = {"permissions": {"allow": ["read_file(/tmp/x/**)", "write_file(/work/a.ts)",
                                              "command(rg)", "read_file(/work)"]}, "other": 1}
        argv, _ = self.build("agy", agy_settings=json.dumps(settings))
        obj = json.loads(argv[argv.index("--settings") + 1])
        self.assertEqual(obj["other"], 1)
        self.assertEqual(obj["permissions"]["allow"],
                         ["read_file(/tmp/x)", "read_file(/private/tmp/x)", "write_file(/work/a.ts)",
                          "command(rg)", "read_file(/work)"])
        self.assertFalse(any("*" in r for r in obj["permissions"]["allow"]))

    def test_invalid_options_rejected_before_any_job(self):
        with tempfile.TemporaryDirectory() as d:
            b = ab.Bridge(os.path.join(d, "s"))
            bad = [dict(provider="agy", effort="extreme"), dict(provider="codex", allowed_tools=["Read"]),
                   dict(provider="claude", model="--dangerously-skip-permissions"),
                   dict(provider="claude", parent_id="../escape"), dict(provider="nope")]
            for kw in bad:
                with self.subTest(**{k: str(v) for k, v in kw.items()}), self.assertRaises(ValueError):
                    b.start_agent(kw.pop("provider"), "p", cwd=d, **kw)
            self.assertEqual(b.list_runs(), [])


class CleanupTests(BridgeTestCase):
    def test_cleanup_removes_only_disposables_and_never_follows_symlinks(self):
        cli = self.fake("claude", {"version": "2.1.325", "stdout_lines": CLAUDE_OK})
        deliverable = os.path.join(self.project, "deliverable.md")
        unrelated = os.path.join(self.project, "unrelated.txt")
        victim = os.path.join(self.tmp, "victim.txt")
        for p in (deliverable, unrelated, victim):
            with open(p, "w") as f:
                f.write("keep " + p)
        job = self.start("claude", cli_override=cli, model="m", artifacts=[deliverable])
        jid, rd = job["job_id"], job["run_dir"]
        self.await_event(jid, {"job.completed"})
        foreign = os.path.join(self.root, "runs", "not-ours.txt")
        with open(foreign, "w") as f:
            f.write("foreign")
        # hostile planting: symlinks inside the run dir pointing at files we must not touch
        os.symlink(victim, os.path.join(rd, "tmp", "link-to-victim"))
        os.unlink(os.path.join(rd, "stderr.log"))
        os.symlink(victim, os.path.join(rd, "stderr.log"))

        refused = self.b.cleanup_run(jid)
        self.assertFalse(refused["ok"])
        self.assertTrue(os.path.exists(os.path.join(rd, "prompt.txt")))

        self.b.acknowledge(jid, "reviewed")
        rep = self.b.cleanup_run(jid)
        self.assertTrue(rep["ok"], rep)
        self.assertIn("prompt.txt", rep["removed"])
        self.assertIn("stdout.log", rep["removed"])
        self.assertIn("tmp/", rep["removed"])
        self.assertIn("stderr.log", [p["name"] for p in rep["preserved"]])
        self.assertEqual(rep["cleanup_status"], "partial")
        for p in (deliverable, unrelated, victim):
            with open(p) as f:
                self.assertEqual(f.read(), "keep " + p)
        with open(foreign) as f:
            self.assertEqual(f.read(), "foreign")
        for kept in ("summary.json", "result.md", "manifest.json"):
            self.assertTrue(os.path.isfile(os.path.join(rd, kept)), kept)
        self.assertFalse(os.path.exists(os.path.join(rd, "prompt.txt")))
        self.assertTrue(os.path.islink(os.path.join(rd, "stderr.log")))
        with open(os.path.join(rd, "manifest.json")) as f:
            self.assertIsNotNone(json.load(f)["cleanup"])
        self.assertEqual(self.b.get_status(jid)["cleanup_status"], "partial")
        self.assertEqual(self.b.get_result(jid)["result_text"], "DONE")

    def test_artifact_inside_scratch_dir_preserves_that_dir(self):
        cli = self.fake("claude", {"version": "2.1.325", "stdout_lines": CLAUDE_OK})
        job = self.start("claude", cli_override=cli, model="m")
        self.await_event(job["job_id"], {"job.completed"})
        art = os.path.join(job["run_dir"], "tmp", "report.md")
        with open(art, "w") as f:
            f.write("deliverable")
        self.b.add_artifact(job["job_id"], art)
        self.b.acknowledge(job["job_id"])
        rep = self.b.cleanup_run(job["job_id"])
        self.assertIn({"name": "tmp", "reason": "contains a declared artifact"}, rep["preserved"])
        with open(art) as f:
            self.assertEqual(f.read(), "deliverable")

    def test_running_job_cannot_be_cleaned_but_cancelled_job_can(self):
        cli = self.fake("claude", {"version": "2.1.325", "sleep": 60, "stdout_lines": CLAUDE_OK})
        job = self.start("claude", cli_override=cli, model="m")
        self.await_event(job["job_id"], {"job.started"})
        self.assertFalse(self.b.cleanup_run(job["job_id"], require_ack=False)["ok"])
        with self.assertRaises(RuntimeError):
            self.b.acknowledge(job["job_id"])
        self.b.cancel_agent(job["job_id"])
        self.b.acknowledge(job["job_id"])
        rep = self.b.cleanup_run(job["job_id"])
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["cleanup_status"], "cleaned")

    def test_path_traversal_job_ids_rejected(self):
        for bad in ("../state", "job-../../x", "/etc", "job-20260101T000000Z-zzzzzzzz"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.b.cleanup_run(bad)


class WatchAndCliTests(BridgeTestCase):
    def test_watch_external_transcript_records_final_result_read_only(self):
        tr = os.path.join(self.tmp, "external.jsonl")
        with open(tr, "w") as f:
            f.write('{"type":"system","subtype":"init","session_id":"ext-1","model":"claude-opus-5-5"}\n')
        w = self.b.watch_transcript(tr, parent_id="parent", label="opus-builder", settle_seconds=0.5,
                                    poll_seconds=0.2)
        self.await_event(w["job_id"], {"job.started"})
        time.sleep(0.6)
        self.assertFalse(self.b.get_status(w["job_id"])["terminal"])
        with open(tr, "a") as f:
            f.write('{"type":"result","subtype":"success","is_error":false,"result":"UI done","session_id":"ext-1"}\n')
        with open(tr, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        ev = self.await_event(w["job_id"], {"job.completed", "job.failed"})
        self.assertEqual(ev["type"], "job.completed")
        self.assertEqual((ev["payload"]["session_id"], ev["payload"]["result_preview"]), ("ext-1", "UI done"))
        with open(tr, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest)
        self.b.acknowledge(w["job_id"])
        self.b.cleanup_run(w["job_id"])
        self.assertTrue(os.path.isfile(tr))

    def test_json_cli_start_then_wait(self):
        cli = self.fake("codex", {"stdout_lines": ['{"type":"thread.started","thread_id":"t1"}',
                                                    '{"type":"turn.completed"}'], "last_message": "ok"})
        script = os.path.join(SCRIPTS, "agent_bridge.py")
        req = json.dumps({"provider": "codex", "prompt": "hi", "cwd": self.project, "parent_id": "cli-parent",
                          "cli_override": cli, "model": "gpt-x", "effort": "low"})
        p = subprocess.run([sys.executable, script, "--root", self.root, "start", req],
                           capture_output=True, text=True, timeout=60)
        out = json.loads(p.stdout)
        self.assertTrue(out["ok"], out)
        jid = out["result"]["job_id"]
        p = subprocess.run([sys.executable, script, "--root", self.root, "wait", "parent_id=cli-parent",
                            'types=["job.completed","job.failed"]', "timeout=30"],
                           capture_output=True, text=True, timeout=60)
        res = json.loads(p.stdout)["result"]
        self.assertEqual([(e["job_id"], e["type"]) for e in res["events"]], [(jid, "job.completed")])
        bad = subprocess.run([sys.executable, script, "--root", self.root, "status", "job_id=../x"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(json.loads(bad.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
