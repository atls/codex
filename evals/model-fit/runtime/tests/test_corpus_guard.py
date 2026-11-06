"""Replay recorded ordinary-turn lock refusals against the actual hook guard."""

import sys
from pathlib import Path

sys.path.insert(
    0, str((Path(__file__).resolve().parents[4] / "plugins/model-fit") / "src")
)

import json
import os
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from model_fit import api as HANDOFF_GUARDS
import model_fit.infrastructure.handoff.state.files as HANDOFF_STATE


@unittest.skipUnless(
    os.environ.get("MODEL_FIT_CORPUS_ROOT"),
    "Private observation corpus is selected explicitly",
)
class RecordedGuardRegressionTests(unittest.TestCase):
    def test_admitted_real_turns_remain_admitted_while_state_lock_is_held(self):
        root = Path(os.environ["MODEL_FIT_CORPUS_ROOT"])
        cases = []
        for source in sorted((root / "cases").glob("*.json")):
            record = json.loads(source.read_text())
            if record.get("collected", {}).get("observed_outcome") in {
                "ordinary_turn_false_block_on_guard_lock",
                "ordinary_turn_false_block_after_auto_pass",
            }:
                cases.append(record)
        self.assertTrue(cases, "No source-backed guard refusals were selected")
        with tempfile.TemporaryDirectory(prefix="model-fit-corpus-regression-") as home:
            with patch.dict(os.environ, {"CODEX_HOME": home}):
                for case in cases:
                    thread, turn = case["thread_id"], case["source_turn_id"]
                    with self.subTest(thread=thread, turn=turn):
                        path = HANDOFF_STATE.state_path(thread)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        HANDOFF_STATE.write_state(
                            path, {"phase": "passed", "source_turn_id": turn}
                        )
                        with HANDOFF_STATE.locked_state(
                            thread, operation="prompt_submit", turn_id=turn
                        ):
                            result = HANDOFF_GUARDS.guard_tool(
                                {
                                    "session_id": thread,
                                    "turn_id": turn,
                                    "tool_name": "Bash",
                                    "tool_input": {"command": "true"},
                                }
                            )
                        self.assertIsNone(result)
                        rows = [
                            json.loads(line)
                            for line in (
                                Path(home)
                                / ".tmp/model-fit-hook-audit"
                                / (thread + ".jsonl")
                            )
                            .read_text()
                            .splitlines()
                        ]
                        self.assertEqual(
                            rows[-1]["details"]["reason_code"], "passed_same_turn"
                        )
