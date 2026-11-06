import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "corpus_native_trace", Path(__file__).resolve().parents[1] / "trace.py"
)
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)


class NativeTraceTests(unittest.TestCase):
    def test_exact_identity_projection_excludes_prewarm_and_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "trace.sqlite"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    "create table traces(trace_id text,evaluation_id text); create table spans(trace_id text,span_id text,parent_span_id text,name text,start_time integer,end_time integer,status_code integer,attributes text);"
                )
                connection.execute(
                    "insert into traces values (?,?)", ("trace", "wanted")
                )
                spans = [
                    (
                        "turn",
                        None,
                        "session_task.turn",
                        {
                            "thread.id": "thread",
                            "turn.id": "turn",
                            "model": "expected",
                            "codex.turn.reasoning_effort": "medium",
                        },
                    ),
                    (
                        "sample",
                        "turn",
                        "run_sampling_request",
                        {"turn_id": "turn", "model": "expected"},
                    ),
                    (
                        "transport",
                        "sample",
                        "model_client.stream_responses_websocket",
                        {"model": "expected"},
                    ),
                    (
                        "prewarm",
                        None,
                        "model_client.stream_responses_websocket",
                        {"model": "unrelated-prewarm"},
                    ),
                ]
                for identity, parent, name, attributes in spans:
                    attributes.update(
                        {
                            "service.name": "codex-app-server",
                            "authorization": "must-not-export",
                            "input": "must-not-export",
                        }
                    )
                    connection.execute(
                        "insert into spans values (?,?,?,?,?,?,?,?)",
                        (
                            "trace",
                            identity,
                            parent,
                            name,
                            1,
                            2,
                            0,
                            json.dumps(attributes),
                        ),
                    )
            request = {
                "database": str(database),
                "evaluationId": "wanted",
                "threadId": "thread",
                "turnId": "turn",
                "model": "expected",
                "effort": "medium",
            }
            result = TRACE.collect(request)
            self.assertEqual(result["status"], "confirmed")
            self.assertEqual(result["executionModel"], "expected")
            self.assertEqual(result["transportCount"], 1)
            self.assertEqual(result["samplingCount"], 1)
            self.assertEqual(
                TRACE.collect(request | {"turnId": "other"})["status"], "unknown"
            )
            self.assertEqual(
                TRACE.collect(request | {"evaluationId": "other"})["status"], "unknown"
            )
            self.assertEqual(
                TRACE.collect(request | {"model": "other"})["status"], "mismatch"
            )
            exported = json.dumps(result)
            for excluded in ("must-not-export", "authorization", "unrelated-prewarm"):
                self.assertNotIn(excluded, exported)
            self.assertTrue(all(span["statusCode"] == 0 for span in result["spans"]))

    def test_failed_network_path_does_not_prove_execution_and_retry_is_retained(self):
        def span(identity, parent, name, **values):
            return (
                dict.fromkeys(
                    [
                        "traceId",
                        "spanId",
                        "parentSpanId",
                        "name",
                        "start",
                        "end",
                        "statusCode",
                        *TRACE.FIELDS,
                    ]
                )
                | {
                    "traceId": "trace",
                    "spanId": identity,
                    "parentSpanId": parent,
                    "name": name,
                    "statusCode": 0,
                    "service": "codex-app-server",
                }
                | values
            )

        rows = [
            span(
                "turn",
                None,
                "session_task.turn",
                threadId="thread",
                turnId="turn",
                model="expected",
                effort="medium",
            ),
            span(
                "sample",
                "turn",
                "run_sampling_request",
                samplingTurnId="turn",
                model="expected",
            ),
            span(
                "client",
                "sample",
                "model_client.stream_responses_websocket",
                model="expected",
            ),
            span(
                "failed", "client", "responses_websocket.stream_request", statusCode=2
            ),
        ]
        failed = TRACE.project(rows, "thread", "turn", "expected", "medium")
        self.assertEqual(failed["status"], "unknown")
        self.assertEqual(failed["successfulTransportCount"], 0)
        rows.append(span("success", "client", "responses_websocket.stream_request"))
        succeeded = TRACE.project(rows, "thread", "turn", "expected", "medium")
        self.assertEqual(succeeded["status"], "confirmed")
        self.assertEqual(succeeded["successfulTransportCount"], 1)
        self.assertEqual(succeeded["transientErrorCount"], 1)
