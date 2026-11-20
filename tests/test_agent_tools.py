"""Behavior checks for the concise caller interface; no real provider calls."""
import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import agent_tools as tools  # noqa: E402
from test_agent_bridge import FAKE_TEMPLATE  # noqa: E402


class AgentToolsTests(unittest.TestCase):
    def test_run_returns_answer_without_exposing_bridge_internals(self):
        b = mock.Mock()
        b.start_agent.return_value = {"job_id": "job-1"}
        b.get_status.return_value = {"status": "completed", "terminal": True,
                                     "provider": "codex", "model": "gpt-6.1-sol",
                                     "failure_reason": None, "artifacts": []}
        b.get_result.return_value = {"result_text": "The answer", "result_path": "/tmp/result.md",
                                     "summary": {"model_reported": "gpt-6.1-sol"}}
        with mock.patch.object(tools.bridge, "Bridge", return_value=b), \
             mock.patch.object(tools.bridge, "recommend_model", return_value={
                 "ok": True, "model": "gpt-6.1-sol", "effort": None}):
            result = tools.run("codex", cwd="/project", prompt="Review the code", task="implementation")
        self.assertEqual(result["answer"], "The answer")
        self.assertEqual(result["status"], "completed")
        b.start_agent.assert_called_once()
        self.assertEqual(b.start_agent.call_args.kwargs["model"], "gpt-6.1-sol")
        b.acknowledge.assert_not_called()
        b.cleanup_run.assert_not_called()

    def test_run_uses_same_cli_for_recommendation_and_execution(self):
        b = mock.Mock()
        b.start_agent.return_value = {"job_id": "job-1"}
        with mock.patch.object(tools.bridge, "Bridge", return_value=b), \
             mock.patch.object(tools.bridge, "recommend_model", return_value={
                 "ok": True, "model": "gemini-4-hydrogen-high", "effort": "high"}) as recommend, \
             mock.patch.object(tools, "collect", return_value={"job_id": "job-1", "status": "running"}):
            tools.run("agy", cwd="/project", prompt="Do work", task="implementation",
                      cli_override="/test/agy")
        recommend.assert_called_once_with("agy", "implementation", "/test/agy")

    def test_pending_job_returns_id_for_later_collect(self):
        b = mock.Mock()
        b.get_status.return_value = {"status": "running", "terminal": False,
                                     "provider": "agy", "model": None,
                                     "failure_reason": None, "artifacts": []}
        with mock.patch.object(tools.bridge, "Bridge", return_value=b):
            result = tools.collect("job-2", wait_seconds=0)
        self.assertEqual(result["job_id"], "job-2")
        self.assertIsNone(result["answer"])
        b.get_result.assert_not_called()

    def test_finish_requires_review_and_preserves_harness_cleanup_checks(self):
        b = mock.Mock()
        b.acknowledge.return_value = {"status": "acknowledged"}
        b.cleanup_run.return_value = {"cleanup_status": "cleaned"}
        with mock.patch.object(tools.bridge, "Bridge", return_value=b):
            with self.assertRaises(ValueError):
                tools.finish("job-3")
            result = tools.finish("job-3", reviewed=True, note="Checked output")
        self.assertEqual(result["cleanup"]["cleanup_status"], "cleaned")
        b.acknowledge.assert_called_once_with("job-3", "Checked output")
        b.cleanup_run.assert_called_once_with("job-3")

    def test_explicit_effort_is_not_silently_changed(self):
        with mock.patch.object(tools.bridge, "recommend_model", return_value={
                "ok": True, "model": "gemini-4-hydrogen-high", "effort": "high"}):
            with self.assertRaises(ValueError):
                tools.run("agy", cwd="/project", prompt="Do work", task="implementation", effort="xhigh")

    def test_run_collect_and_finish_with_fake_codex(self):
        root = tempfile.mkdtemp(prefix="agent-tools-test-")
        try:
            scenario = {"stdout_lines": [
                '{"type":"thread.started","thread_id":"tool-test-session"}',
                '{"type":"turn.completed","usage":{"input_tokens":1}}'],
                "last_message": "ANSWER_FROM_PROVIDER"}
            with open(os.path.join(root, "codex.scenario.json"), "w") as f:
                json.dump(scenario, f)
            fake = os.path.join(root, "codex")
            with open(fake, "w") as f:
                f.write(FAKE_TEMPLATE.format(python=sys.executable, name="codex"))
            os.chmod(fake, 0o755)
            arguments = os.path.join(root, "run.json")
            with open(arguments, "w") as f:
                json.dump({"provider": "codex", "cwd": root, "prompt": "Reply with the answer",
                           "cli_override": fake, "run_root": os.path.join(root, "state"),
                           "wait_seconds": 10}, f)
            proc = subprocess.run([sys.executable, tools.__file__, "run", "--json-file", arguments],
                                  capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            result = json.loads(proc.stdout)["result"]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["answer"], "ANSWER_FROM_PROVIDER")
            self.assertEqual(tools.collect(result["job_id"], wait_seconds=0,
                                           run_root=os.path.join(root, "state"))["answer"],
                             "ANSWER_FROM_PROVIDER")
            finished = tools.finish(result["job_id"], reviewed=True,
                                    run_root=os.path.join(root, "state"))
            self.assertEqual(finished["cleanup"]["cleanup_status"], "cleaned")
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
