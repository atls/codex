import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "collect-traces.py"
SPEC = importlib.util.spec_from_file_location("corpus_trace_projection", PATH)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


class CorpusTraceProjectionTests(unittest.TestCase):
    def test_uses_exact_executor_ids_and_existing_native_trace_owner(self):
        result = {
            "evalId": "evaluation",
            "results": [
                {
                    "testCase": {"description": "fixture"},
                    "response": {
                        "metadata": {
                            "mode": "model-fit",
                            "model_fit_invoked": True,
                            "execution_profile": {"model": "model", "effort": "medium"},
                            "corpusStages": {
                                "execution": {
                                    "status": "completed",
                                    "response": {
                                        "metadata": {
                                            "codexAppServer": {
                                                "threadId": "executor-thread",
                                                "turnId": "executor-turn",
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    },
                }
            ],
        }
        with patch.object(
            COLLECTOR.TRACE,
            "collect",
            return_value={"status": "confirmed", "executionModel": "model"},
        ) as native:
            rows = COLLECTOR.collect(result, "/fixture/database")
        self.assertEqual(
            native.call_args.args[0],
            {
                "database": "/fixture/database",
                "evaluationId": "evaluation",
                "threadId": "executor-thread",
                "turnId": "executor-turn",
                "model": "model",
                "effort": "medium",
            },
        )
        self.assertEqual(rows[0]["executionTrace"]["status"], "confirmed")
        self.assertEqual(rows[0]["preflightTrace"]["status"], "unknown")

    def test_not_invoked_is_not_unknown_or_an_invented_execution(self):
        result = {
            "results": {
                "results": [
                    {
                        "testCase": {"description": "fixture"},
                        "response": {
                            "metadata": {
                                "mode": "stock-control",
                                "model_fit_invoked": False,
                                "corpusStages": {
                                    "execution": {"status": "not-invoked"}
                                },
                            }
                        },
                    }
                ]
            }
        }
        with patch.object(
            COLLECTOR.TRACE, "collect", side_effect=AssertionError("No trace identity")
        ):
            rows = COLLECTOR.collect(result, "/fixture/database")
        self.assertEqual(rows[0]["executionTrace"]["status"], "not-invoked")
        self.assertEqual(rows[0]["preflightTrace"]["status"], "not-invoked")
