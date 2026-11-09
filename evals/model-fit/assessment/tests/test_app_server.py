"""Process and protocol regression checks for the shared stdio transport."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
from model_fit.infrastructure.adapters.codex.transport.connection import (
    AppServerConnection,
    AppServerRPCError,
)


class AppServerTransportTests(unittest.TestCase):
    def connection(self):
        app = object.__new__(AppServerConnection)
        app.next_id = 0
        app.events = []
        app.pending = b""
        app.timeout_message = "timeout"
        app.closed_message = "closed"
        app.close_timeout = 3
        return app

    def test_rpc_notifications_keep_wire_order_before_response_and_completion(self):
        app = self.connection()
        first = {"method": "item/started", "params": {"item": {"id": "tool"}}}
        unrelated = {
            "method": "turn/completed",
            "params": {"threadId": "other", "turn": {"id": "turn", "status": "failed"}},
        }
        completed = {
            "method": "turn/completed",
            "params": {
                "threadId": "thread",
                "turn": {"id": "turn", "status": "completed"},
            },
        }
        with (
            patch.object(app, "send"),
            patch.object(
                app,
                "read",
                side_effect=[
                    first,
                    {"id": 0, "result": {"turn": {"id": "turn"}}},
                    unrelated,
                    completed,
                ],
            ),
        ):
            app.call("turn/start", {"threadId": "thread"}, 1)
            self.assertEqual(app.wait_turn("thread", "turn", 1), "completed")
        self.assertEqual(app.events, [first, unrelated, completed])

    def test_structured_rpc_failure_retains_exact_method_code_and_requested_thread(
        self,
    ):
        app = self.connection()
        with (
            patch.object(app, "send"),
            patch.object(
                app,
                "read",
                return_value={
                    "id": 0,
                    "error": {"code": -32600, "message": "thread not loaded: thread"},
                },
            ),
        ):
            with self.assertRaises(AppServerRPCError) as caught:
                app.call("thread/read", {"threadId": "thread"}, 1)
        error = caught.exception
        self.assertEqual(
            (error.method, error.code, error.rpc_message, error.thread_id),
            ("thread/read", -32600, "thread not loaded: thread", "thread"),
        )

    def test_malformed_error_and_unexpected_server_request_stop_the_call(self):
        for event, expected in [
            ({"id": 0, "error": {"code": -32600}}, ValueError),
            ({"id": 9, "method": "approval/request"}, RuntimeError),
        ]:
            app = self.connection()
            with (
                self.subTest(event=event),
                patch.object(app, "send"),
                patch.object(app, "read", return_value=event),
                self.assertRaises(expected),
            ):
                app.call("thread/read", {}, 1)

    def test_initialization_failure_closes_process_without_waiting_for_a_turn(self):
        process = Mock()
        with (
            patch.object(
                AppServerConnection, "call", side_effect=RuntimeError("initialize")
            ),
            patch.object(AppServerConnection, "close") as close,
            self.assertRaises(RuntimeError),
        ):
            AppServerConnection(process, {"name": "fixture", "version": "1"})
        close.assert_called_once()

    def test_close_reaps_a_real_process_after_termination_timeout(self):
        import select
        import signal

        app = self.connection()
        app.close_timeout = 0.5
        app.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(30)",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertTrue(select.select([app.process.stdout], [], [], 5)[0])
            self.assertEqual(app.process.stdout.readline().strip(), b"ready")
            app.close()
            self.assertEqual(app.process.poll(), -signal.SIGKILL)
            self.assertTrue(
                all(
                    stream.closed
                    for stream in (
                        app.process.stdin,
                        app.process.stdout,
                        app.process.stderr,
                    )
                )
            )
        finally:
            if app.process.poll() is None:
                app.process.kill()
                app.process.wait(timeout=5)
            for stream in (app.process.stdin, app.process.stdout, app.process.stderr):
                stream.close()

    def test_real_process_fragmented_lines_and_eof(self):
        script = "import sys,time; sys.stdout.write('{\\\"id\\\":'); sys.stdout.flush(); time.sleep(.03); print('7}'); print('{\\\"id\\\":8}')"
        app = self.connection()
        app.process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        try:
            import time

            self.assertEqual(app.read(time.monotonic() + 2), {"id": 7})
            self.assertEqual(app.read(time.monotonic() + 2), {"id": 8})
            with self.assertRaisesRegex(RuntimeError, "closed"):
                app.read(time.monotonic() + 2)
        finally:
            app.close()
            app.process.stdin.close()
            app.process.stdout.close()

    def test_read_timeout_remains_bounded_for_a_silent_real_process(self):
        import time

        app = self.connection()
        app.process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        try:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                app.read(started + 0.05)
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            app.close()
            app.process.stdin.close()
            app.process.stdout.close()

    def test_live_reader_keeps_live_home_and_original_process_flags(self):
        from model_fit.infrastructure.adapters.codex.history import AppServerReader

        with (
            patch(
                "model_fit.infrastructure.adapters.codex.transport.reader.subprocess.Popen"
            ) as spawn,
            patch.object(AppServerReader, "call", return_value={}),
            patch.object(AppServerReader, "send"),
        ):
            reader = AppServerReader("/fixture/project")
            try:
                args, kwargs = spawn.call_args
                self.assertEqual(
                    args[0],
                    [
                        "codex",
                        "app-server",
                        "--listen",
                        "stdio://",
                        "-c",
                        "features.hooks=false",
                    ],
                )
                self.assertNotIn("env", kwargs)
                self.assertEqual(kwargs["cwd"], "/fixture/project")
                self.assertFalse(hasattr(reader, "home"))
            finally:
                reader.close()
