"""Checks for thread and permission operations against a throwaway home folder; no model calls."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import agent_admin as admin  # noqa: E402

THREAD = "fd9a3bbf-0cd5-4249-a799-800b7e320bb3"


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agent-admin-test-")
        self.p = admin._paths(self.home)
        # A fixed test policy, independent of the user's current (possibly empty) deny list.
        policy = os.path.join(self.home, "policy.json")
        with open(policy, "w") as f:
            json.dump({"deny_commands": [["git", "push"], ["git", "commit"], ["git", "-C"], ["git", "-c"],
                                         ["git", "--git-dir"], ["rm", "-rf"]],
                       "antigravity_allow": ["read_file(~/Documents/GitHub)", "command(git status)"],
                       "codex_web_search": "live", "codex_network_access": True}, f)
        patcher = mock.patch.dict(os.environ, {"AGENT_PERMISSION_POLICY": policy})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.makedirs(os.path.dirname(self.p["antigravity_app"]))
        with open(self.p["antigravity_app"], "w") as f:
            json.dump({"plugins": {"x": 1}, "userSettings": {
                "permissionPreset": "AGENT_PERMISSION_PRESET_TURBO",
                "globalPermissionGrants": {"allow": ["read_file(/keep)"]}}}, f)
        os.makedirs(os.path.dirname(self.p["codex_config"]))
        with open(self.p["codex_config"], "w") as f:
            f.write('model = "m"\n\n[sandbox_workspace_write]\nnetwork_access = false\n\n[other]\nkey = 1\n')

    def tearDown(self):
        shutil.rmtree(self.home)

    def test_status_reports_everything_missing_on_a_fresh_home(self):
        status = admin.permissions_status(home=self.home)
        self.assertEqual(status["ok"], {"antigravity": False, "codex": False, "claude": False})
        self.assertIn("command(git -C)", status["antigravity_cli"]["missing_deny"])
        self.assertIn("git push", status["codex"]["missing_deny"])
        self.assertEqual(status["codex"]["network_access"], "false")

    def test_apply_needs_approval_and_dry_run_writes_nothing(self):
        with self.assertRaises(ValueError):
            admin.permissions_apply(home=self.home)
        preview = admin.permissions_apply(dry_run=True, home=self.home)
        self.assertTrue(preview["changes"])
        self.assertFalse(os.path.exists(self.p["antigravity_cli"]))
        self.assertFalse(os.path.exists(self.p["codex_rules"]))

    def test_apply_merges_policy_keeps_other_settings_and_is_idempotent(self):
        result = admin.permissions_apply(user_approved=True, home=self.home)
        self.assertEqual(result["status_after"], {"antigravity": True, "codex": True, "claude": False})
        app = json.load(open(self.p["antigravity_app"]))
        self.assertEqual(app["plugins"], {"x": 1})
        self.assertEqual(app["userSettings"]["globalPermissionGrants"]["allow"], ["read_file(/keep)"])
        self.assertIn("command(git push)", app["userSettings"]["globalPermissionGrants"]["deny"])
        config = open(self.p["codex_config"]).read()
        self.assertIn('web_search = "live"', config.split("\n[", 1)[0])
        self.assertIn("network_access = true", config)
        self.assertNotIn("network_access = false", config)
        self.assertIn("[other]\nkey = 1", config)
        cli = json.load(open(self.p["antigravity_cli"]))
        self.assertIn(f"read_file({self.home}/Documents/GitHub)", cli["permissions"]["allow"])
        self.assertTrue(any(c.get("backup") for c in result["changes"]))
        self.assertEqual(admin.permissions_apply(user_approved=True, home=self.home)["changes"], [])

    def test_claude_is_only_changed_when_requested(self):
        admin.permissions_apply(user_approved=True, tools=["claude"], home=self.home)
        claude = json.load(open(self.p["claude"]))
        self.assertIn("Bash(git push:*)", claude["permissions"]["deny"])
        self.assertFalse(os.path.exists(self.p["antigravity_cli"]))

    @unittest.skipUnless(admin._codex_cli(), "codex CLI not installed")
    def test_generated_codex_rules_block_every_deny_entry(self):
        admin.permissions_apply(user_approved=True, tools=["codex"], home=self.home)
        result = admin.permissions_test(tools=["codex"], home=self.home)
        self.assertTrue(result["codex_static"]["pass"], result["codex_static"])


class ThreadTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="agent-thread-test-")
        log = os.path.join(admin._paths(self.home)["brain"], THREAD, ".system_generated", "logs")
        os.makedirs(log)
        rows = [{"type": "USER_INPUT", "content": "<USER_REQUEST>\nIs task 2 done?\n</USER_REQUEST>", "created_at": "t1"},
                {"type": "PLANNER_RESPONSE", "content": "", "created_at": "t2"},
                {"type": "PLANNER_RESPONSE", "content": "Not yet.", "created_at": "t3"}]
        with open(os.path.join(log, "transcript.jsonl"), "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows) + "\n")

    def tearDown(self):
        shutil.rmtree(self.home)

    def test_read_returns_user_and_agent_messages(self):
        result = admin.thread_read(THREAD, home=self.home)
        self.assertEqual([m["text"] for m in result["messages"]], ["Is task 2 done?", "Not yet."])
        with self.assertRaises(ValueError):
            admin.thread_read("not-an-id", home=self.home)

    def test_ask_uses_the_app_data_dir_and_flags_empty_answers(self):
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps({"response": "", "denied_actions": []}),
                                           stderr='a tool required the "command" permission')
        with mock.patch.object(admin.subprocess, "run", return_value=done) as run:
            result = admin.thread_ask(THREAD, prompt="Question", sender="Claude", home=self.home)
        argv = run.call_args.args[0]
        self.assertIn("--app_data_dir=antigravity", argv)
        self.assertEqual(argv[argv.index("--conversation") + 1], THREAD)
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")
        self.assertTrue(argv[-1].startswith("This is Claude"))
        self.assertEqual(result["status"], "no_answer")
        self.assertIn("hint", result)


if __name__ == "__main__":
    unittest.main()
