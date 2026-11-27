import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from pydantic import ValidationError
from vector_prime.application.assessment.helpers.decision import empty_decision
from vector_prime.entrypoints.cli import assess as cli
from vector_prime.infrastructure.adapters.runtime.assessment import triage


class DecisionProvenanceTests(unittest.TestCase):
    active = {"model": "fixture", "effort": "medium", "speed": None}

    def test_cli_provenance_is_opt_in_and_excludes_private_diagnostics(self):
        request = {"task": "private-sentinel", "active_profile": self.active}
        for enabled in (False, True):
            with self.subTest(enabled=enabled):

                def assessment(*args, diagnostics=None, **kwargs):
                    if diagnostics is not None:
                        diagnostics.update(
                            decision_origin="discussion_rule",
                            work_relation="discussion",
                            private_field="private-sentinel",
                        )
                    return empty_decision(self.active, "keep", "Fixture result")

                output = io.StringIO()
                with (
                    patch(
                        "sys.argv",
                        ["vp"] + (["--include-provenance"] if enabled else []),
                    ),
                    patch("sys.stdin", io.StringIO(json.dumps(request))),
                    patch.object(cli, "assess", side_effect=assessment),
                    redirect_stdout(output),
                ):
                    self.assertEqual(cli.main(), 0)
                result = json.loads(output.getvalue())
                self.assertEqual("provenance" in result, enabled)
                self.assertNotIn("private-sentinel", output.getvalue())
                if enabled:
                    self.assertEqual(
                        result["provenance"],
                        {
                            "decision_origin": "discussion_rule",
                            "work_relation": "discussion",
                        },
                    )

    def test_runtime_preserves_validated_provenance_and_accepts_older_results(self):
        request = {"task": "Fixture work", "active_profile": self.active}
        for provenance in (None, {"decision_origin": "user_choice"}):
            result = empty_decision(self.active, "keep", "Fixture result")
            if provenance is not None:
                result["provenance"] = provenance
            with patch(
                "vector_prime.infrastructure.adapters.runtime.assessment.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, json.dumps(result), ""),
            ) as run:
                actual = triage(request)
            self.assertEqual(actual, result)
            self.assertIn("--include-provenance", run.call_args.args[0])

    def test_runtime_rejects_unbounded_or_unknown_provenance(self):
        result = empty_decision(self.active, "keep", "Fixture result")
        for provenance in (
            {"decision_origin": "private-sentinel"},
            {"decision_origin": "evaluator", "work_relation": "unexpected"},
            {"decision_origin": "evaluator", "prompt": "private-sentinel"},
        ):
            result["provenance"] = provenance
            with (
                patch(
                    "vector_prime.infrastructure.adapters.runtime.assessment.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(result), ""
                    ),
                ),
                self.assertRaises(ValidationError),
            ):
                triage({"task": "Fixture work", "active_profile": self.active})
