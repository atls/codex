import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from acceptance.tests.media_fixture import media_context

PATH = Path(__file__).resolve().parents[1] / "grade.py"
SPEC = importlib.util.spec_from_file_location("media_acceptance_grade", PATH)
GRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRADE)


class NativeMediaGradeTests(unittest.TestCase):
    def test_two_media_rows_require_original_native_order_and_hook_proof(self):
        for empty in [False, True]:
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as name:
                context = media_context(Path(name), empty)
                self.assertTrue(
                    GRADE.get_assert(
                        '{"colors":["red","blue"],"imageCount":2}', context
                    )["pass"]
                )
                context["providerResponse"]["raw"]["items"][0]["content"][1:] = list(
                    reversed(
                        context["providerResponse"]["raw"]["items"][0]["content"][1:]
                    )
                )
                self.assertFalse(
                    GRADE.get_assert(
                        '{"colors":["red","blue"],"imageCount":2}', context
                    )["pass"]
                )

    def test_inactive_or_unassessed_hook_cannot_pass_media_acceptance(self):
        for defect in ("inactive", "no-assessment"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                context = media_context(root)
                if defect == "inactive":
                    path = root / "home/acceptance-hook-events.jsonl"
                    row = json.loads(path.read_text())
                    row["state_snapshot"] = None
                    path.write_text(json.dumps(row) + "\n")
                else:
                    (root / "home/.tmp/model-fit-hook-audit/thread.jsonl").write_text(
                        json.dumps({"turn_id": "turn", "outcome": "auto_deferred"})
                        + "\n"
                    )
                self.assertFalse(
                    GRADE.get_assert(
                        '{"colors":["red","blue"],"imageCount":2}', context
                    )["pass"]
                )

    def test_missing_native_hook_or_wrong_state_cannot_claim_acceptance(self):
        for defect in ("missing-hook", "wrong-phase", "foreign-turn"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                context = media_context(root)
                if defect == "missing-hook":
                    context["providerResponse"]["raw"]["notifications"] = []
                else:
                    state = root / "home/.tmp/model-fit-auto-switch/thread.json"
                    state.write_text(
                        json.dumps(
                            {
                                "phase": "ready"
                                if defect == "wrong-phase"
                                else "passed",
                                "source_turn_id": "foreign"
                                if defect == "foreign-turn"
                                else "turn",
                            }
                        )
                    )
                self.assertFalse(
                    GRADE.get_assert(
                        '{"colors":["red","blue"],"imageCount":2}', context
                    )["pass"]
                )
                result = json.loads((root / "evidence/grade.json").read_text())
                self.assertIn(
                    "hook completion"
                    if defect == "missing-hook"
                    else "did not release",
                    result["reason"],
                )

    def test_retained_images_hashes_state_and_audit_allow_offline_grade_after_cleanup(
        self,
    ):
        import hashlib
        import shutil

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            context = media_context(root)
            evidence = root / "evidence"
            retained = []
            for filename in ["first.png", "second.png"]:
                original = root / filename
                destination = evidence / filename
                shutil.copyfile(original, destination)
                retained.append(
                    {
                        "originalPath": str(original),
                        "retainedPath": str(destination),
                        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                    }
                )
                original.unlink()
            shutil.copyfile(
                root / "home/acceptance-hook-events.jsonl",
                evidence / "acceptance-hook-events.jsonl",
            )
            shutil.copytree(root / "home/.tmp/model-fit-hook-audit", evidence / "audit")
            shutil.copytree(
                root / "home/.tmp/model-fit-auto-switch", evidence / "state"
            )
            shutil.rmtree(root / "home")
            context["vars"]["retained_images"] = retained
            self.assertTrue(
                GRADE.get_assert('{"colors":["red","blue"],"imageCount":2}', context)[
                    "pass"
                ]
            )
            (evidence / "first.png").write_bytes(b"changed")
            self.assertFalse(
                GRADE.get_assert('{"colors":["red","blue"],"imageCount":2}', context)[
                    "pass"
                ]
            )
