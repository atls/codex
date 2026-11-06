import sys
from pathlib import Path

sys.path.insert(
    0, str((Path(__file__).resolve().parents[4] / "plugins/model-fit") / "src")
)

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from model_fit.entrypoints.desktop import activation
from model_fit.entrypoints.desktop import cli as ENTRY
from model_fit.entrypoints.desktop import dispatch as GLOBAL
from model_fit.entrypoints.desktop import lifecycle as CLI
from model_fit.infrastructure.codex import hooks as NATIVE_HOOKS


class GlobalHookTests(unittest.TestCase):
    def setUp(self):
        admission = patch.object(GLOBAL, "automatic_allowed", return_value=True)
        admission.start()
        self.addCleanup(admission.stop)

    def test_admission_uses_own_native_hook_source_across_marketplaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition = root / "hooks/hooks.json"
            definition.parent.mkdir()
            definition.write_text("{}")
            (root / ".codex-plugin").mkdir()
            (root / ".codex-plugin/plugin.json").write_text(
                json.dumps({"name": "model-fit"})
            )
            plugin = "model-fit@regression-fixtures"
            config = {
                "features": {"hooks": True},
                "plugins": {
                    "model-fit@agent-tools": {"enabled": False},
                    plugin: {"enabled": True},
                },
            }
            hook = {
                "sourcePath": str(definition),
                "pluginId": plugin,
                "eventName": "preToolUse",
                "enabled": True,
                "trustStatus": "trusted",
            }
            reader = MagicMock()
            reader.__enter__.return_value.call.side_effect = (
                lambda method, params, timeout: (
                    {"config": config}
                    if method == "config/read"
                    else {"data": [{"hooks": [hook]}]}
                )
            )
            with (
                patch.dict(os.environ, {"CODEX_PLUGIN_ROOT": directory}),
                patch.object(NATIVE_HOOKS, "AppServerReader", return_value=reader),
            ):
                self.assertIs(NATIVE_HOOKS.hook_enabled("PreToolUse", directory), True)
                config["plugins"][plugin]["enabled"] = False
                config["plugins"]["model-fit@agent-tools"]["enabled"] = True
                self.assertIs(NATIVE_HOOKS.hook_enabled("PreToolUse", directory), False)
                config["plugins"][plugin]["enabled"] = True
                for changes in (
                    {"enabled": False},
                    {"trustStatus": "modified"},
                    {"sourcePath": str(root / "other/hooks.json")},
                ):
                    with self.subTest(changes=changes), patch.dict(hook, changes):
                        self.assertIs(
                            NATIVE_HOOKS.hook_enabled("PreToolUse", directory), False
                        )

    def test_automatic_commands_require_registered_scope_without_legacy_fallback(self):
        for arguments in (
            ["assess"],
            ["queue", "--thread-id", "current", "--turn-id", "source"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(activation, "hook_enabled", return_value=None),
                patch.object(ENTRY, "assess_current") as assess,
                patch.object(ENTRY, "queue_handoff") as queue,
                redirect_stdout(io.StringIO()) as output,
            ):
                status = ENTRY.main(arguments)
                assess.assert_not_called()
                queue.assert_not_called()
                self.assertEqual(status, 1 if arguments[0] == "queue" else 0)
                self.assertNotIn("пригодность подтверждена", output.getvalue())

    def test_dispatches_all_events_and_chat_paths_in_active_home(self):
        for home in ("/fixture/primary", "/fixture/secondary"):
            for cwd in (
                "/fixture/project",
                "/fixture/project/worktree",
                "/fixture/.chatgpt-projects/design",
            ):
                for event_name in ("UserPromptSubmit", "PreToolUse", "Stop"):
                    event = {
                        "session_id": "new-chat-id",
                        "hook_event_name": event_name,
                        "cwd": cwd,
                    }
                    raw = json.dumps(event)
                    with (
                        self.subTest(home=home, cwd=cwd, event=event_name),
                        patch.dict(
                            os.environ,
                            {"CODEX_HOME": home, "MODEL_FIT_AUTO_THREAD": "stale-id"},
                        ),
                        patch.object(sys, "stdin", io.StringIO(raw)),
                        patch.object(GLOBAL, "handle_lifecycle") as run,
                    ):
                        run.return_value = 0
                        self.assertEqual(GLOBAL.dispatch_hook(), 0)
                        self.assertEqual(
                            run.call_args.kwargs,
                            {"event": event, "expected_thread": "new-chat-id"},
                        )
                        self.assertEqual(os.environ["CODEX_HOME"], home)
                        self.assertEqual(
                            os.environ["MODEL_FIT_AUTO_THREAD"], "stale-id"
                        )

    def test_rejects_invalid_chat_identity_without_launching_handler(self):
        for event in ({}, {"session_id": "../outside"}, {"session_id": 1}, []):
            with (
                self.subTest(event=event),
                patch.object(sys, "stdin", io.StringIO(json.dumps(event))),
                patch.object(GLOBAL, "handle_lifecycle") as run,
            ):
                self.assertEqual(GLOBAL.dispatch_hook(), 0)
                run.assert_not_called()

    def test_preserves_handler_failure(self):
        with (
            patch.object(
                sys,
                "stdin",
                io.StringIO('{"session_id":"chat","hook_event_name":"Stop"}'),
            ),
            patch.object(GLOBAL, "handle_lifecycle") as run,
        ):
            run.return_value = 2
            self.assertEqual(GLOBAL.dispatch_hook(), 2)

    def test_child_dispatch_uses_agent_identity_and_preserves_native_body(self):
        event = {
            "session_id": "parent-thread",
            "agent_id": "child-thread",
            "turn_id": "child-turn",
            "hook_event_name": "PreToolUse",
        }
        raw = json.dumps(event)
        with (
            patch.object(sys, "stdin", io.StringIO(raw)),
            patch.object(GLOBAL, "handle_lifecycle") as run,
        ):
            run.return_value = 0
            self.assertEqual(GLOBAL.dispatch_hook(), 0)
        self.assertEqual(
            run.call_args.kwargs, {"event": event, "expected_thread": "child-thread"}
        )

    def test_revocation_during_assessment_does_not_return_transfer_instructions(self):
        with tempfile.TemporaryDirectory() as home:
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"CODEX_HOME": home, "CODEX_THREAD_ID": "revoked-thread"},
                ),
                patch.object(
                    CLI,
                    "assess_submitted",
                    return_value={"decision": "block", "reason": "old transfer"},
                ),
                patch.object(CLI, "automatic_allowed", return_value=False),
                redirect_stdout(output),
            ):
                self.assertEqual(CLI.assess_current(check_admission=True), 0)
            response = json.loads(output.getvalue())
            self.assertIn("отключ", response["hookSpecificOutput"]["additionalContext"])
            self.assertNotIn("old transfer", output.getvalue())
            audit = json.loads(
                (
                    Path(home) / ".tmp/model-fit-hook-audit/revoked-thread.jsonl"
                ).read_text()
            )
            self.assertEqual(audit["outcome"], "auto_assessment_revoked")

    def test_missing_submission_reports_executor_without_inventing_a_turn(self):
        with tempfile.TemporaryDirectory() as home:
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ, {"CODEX_HOME": home, "CODEX_THREAD_ID": "missing-child"}
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(CLI.assess_current(), 1)
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "status": "failed",
                    "error": "SubmissionUnavailable",
                    "reason_code": "submission_missing",
                },
            )
            audit = json.loads(
                (
                    Path(home) / ".tmp/model-fit-hook-audit/missing-child.jsonl"
                ).read_text()
            )
            self.assertEqual(audit["executor_thread_id"], "missing-child")
            self.assertIsNone(audit["turn_id"])
            self.assertEqual(audit["details"]["reason_code"], "submission_missing")

    def test_inventory_timeout_preserves_already_admitted_ordinary_work(self):
        states = [
            {
                "phase": "passed",
                "source_turn_id": "current-turn",
                "assessment_decision": "keep",
            },
            {
                "phase": "queued",
                "source_turn_id": "source-turn",
                "replay_turn_id": "current-turn",
            },
        ]
        for state in states:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as home:
                path = Path(home) / ".tmp/model-fit-auto-switch/current-thread.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(state))
                before = path.read_bytes()
                event = {
                    "session_id": "current-thread",
                    "turn_id": "current-turn",
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "gh api user --jq .login"},
                }
                with (
                    patch.dict(os.environ, {"CODEX_HOME": home}),
                    patch.object(GLOBAL, "automatic_allowed", return_value=None),
                    patch.object(sys, "stdin", io.StringIO(json.dumps(event))),
                    patch.object(GLOBAL, "handle_lifecycle") as runtime,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    self.assertEqual(GLOBAL.dispatch_hook(), 0)
                self.assertEqual(output.getvalue(), "")
                runtime.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                audit = json.loads(
                    (
                        Path(home) / ".tmp/model-fit-hook-audit/current-thread.jsonl"
                    ).read_text()
                )
                self.assertEqual(audit["outcome"], "auto_hook_admission_unknown")
                self.assertEqual(audit["turn_id"], "current-turn")

    def test_inventory_failure_cannot_admit_new_work_or_automatic_transfers(self):
        from model_fit.entrypoints.desktop import instructions

        passed = {"phase": "passed", "source_turn_id": "current-turn"}
        ordinary = {"tool_name": "Bash", "tool_input": {"command": "pwd"}}
        cases = [
            (None, ordinary),
            ({"phase": "passed", "source_turn_id": "old-turn"}, ordinary),
            (
                {
                    "phase": "passed",
                    "source_turn_id": "current-turn",
                    "pending_assessment": {"status": "waiting"},
                },
                ordinary,
            ),
            ({"phase": "ready", "source_turn_id": "current-turn"}, ordinary),
            (
                {
                    "phase": "queued",
                    "source_turn_id": "current-turn",
                    "replay_turn_id": "other-replay",
                },
                ordinary,
            ),
            ({"phase": "attempting", "source_turn_id": "current-turn"}, ordinary),
            (
                passed,
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": instructions.assessment_command()},
                },
            ),
            (
                passed,
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": instructions.queue_command(
                            "current-thread", "current-turn"
                        )
                    },
                },
            ),
            (
                passed,
                {
                    "tool_name": "mcp__codex_app__send_message_to_thread",
                    "tool_input": {"prompt": instructions.CONTROL_PROMPT},
                },
            ),
        ]
        for state, tool in cases:
            with (
                self.subTest(state=state, tool=tool),
                tempfile.TemporaryDirectory() as home,
            ):
                path = Path(home) / ".tmp/model-fit-auto-switch/current-thread.json"
                path.parent.mkdir(parents=True)
                if state is not None:
                    path.write_text(json.dumps(state))
                before = path.read_bytes() if path.exists() else None
                event = {
                    "session_id": "current-thread",
                    "turn_id": "current-turn",
                    "hook_event_name": "PreToolUse",
                    **tool,
                }
                with (
                    patch.dict(os.environ, {"CODEX_HOME": home}),
                    patch.object(GLOBAL, "automatic_allowed", return_value=None),
                    patch.object(sys, "stdin", io.StringIO(json.dumps(event))),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    self.assertEqual(GLOBAL.dispatch_hook(), 0)
                self.assertEqual(
                    json.loads(output.getvalue())["hookSpecificOutput"][
                        "permissionDecision"
                    ],
                    "deny",
                )
                self.assertEqual(path.read_bytes() if path.exists() else None, before)

    def test_legacy_callback_uses_the_same_admitted_work_query(self):
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / ".tmp/model-fit-auto-switch/child-thread.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"phase": "passed", "source_turn_id": "child-turn"})
            )
            event = {
                "session_id": "parent-thread",
                "agent_id": "child-thread",
                "turn_id": "child-turn",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "pwd"},
            }
            with (
                patch.dict(os.environ, {"CODEX_HOME": home}),
                patch.object(CLI, "automatic_allowed", return_value=None),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(
                    CLI.handle_lifecycle(
                        event=event,
                        expected_thread="child-thread",
                        check_admission=True,
                    ),
                    0,
                )
            self.assertEqual(output.getvalue(), "")
            self.assertFalse((path.parent / "parent-thread.json").exists())

    def test_unavailable_native_admission_does_not_release_tools_or_start_runtime(self):
        event = {
            "session_id": "thread",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "private command"},
        }
        output = io.StringIO()
        with (
            patch.object(
                activation, "hook_enabled", side_effect=TimeoutError("private details")
            ),
            patch.object(sys, "stderr", io.StringIO()) as errors,
        ):
            self.assertIsNone(
                activation.automatic_allowed("PreToolUse", "/tmp", direct=True)
            )
        self.assertNotIn("private details", errors.getvalue())
        with (
            patch.object(GLOBAL, "automatic_allowed", return_value=None),
            patch.object(sys, "stdin", io.StringIO(json.dumps(event))),
            patch.object(GLOBAL, "handle_lifecycle") as run,
            redirect_stdout(output),
            patch.object(GLOBAL, "record_unavailable") as audit,
        ):
            self.assertEqual(GLOBAL.dispatch_hook(), 0)
        run.assert_not_called()
        audit.assert_called_once_with("thread", None, "PreToolUse")
        self.assertEqual(
            json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertNotIn("private command", output.getvalue())
