import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

PATH = Path(__file__).resolve().parents[1] / "grade.py"
SPEC = importlib.util.spec_from_file_location("media_acceptance_grade", PATH)
GRADE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRADE)


class NativeMediaGradeTests(unittest.TestCase):
    def fixture(self, root, empty=False):
        home = root / "home"
        home.mkdir()
        evidence = root / "evidence"
        evidence.mkdir()
        Image.new("RGB", (8, 8), "red").save(root / "first.png")
        Image.new("RGB", (8, 8), "blue").save(root / "second.png")
        prompt = "" if empty else "name colors"
        content = [
            {"type": "text", "text": prompt},
            {"type": "localImage", "path": str(root / "first.png")},
            {"type": "localImage", "path": str(root / "second.png")},
        ]
        warning = json.dumps({"systemMessage": GRADE.WARNING})
        (home / "acceptance-hook-events.jsonl").write_text(
            json.dumps(
                {
                    "event": {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "thread",
                        "turn_id": "turn",
                        "prompt": prompt,
                    },
                    "returncode": 0,
                    "stdout": warning,
                }
            )
            + "\n"
        )
        audit = home / ".tmp/model-fit-hook-audit"
        audit.mkdir(parents=True)
        (audit / "thread.jsonl").write_text(
            json.dumps({"turn_id": "turn", "outcome": "auto_session_unavailable"})
            + "\n"
        )
        state = home / ".tmp/model-fit-auto-switch"
        state.mkdir()
        (state / "thread.json").write_text(
            json.dumps({"phase": "passed", "source_turn_id": "turn"})
        )
        raw = {
            "items": [{"type": "user_message", "content": content}],
            "turn": {"id": "turn", "status": "completed"},
            "notifications": [
                {
                    "method": "hook/completed",
                    "params": {
                        "threadId": "thread",
                        "turnId": "turn",
                        "run": {
                            "eventName": "userPromptSubmit",
                            "status": "completed",
                            "sourcePath": str(home / "hooks.json"),
                            "entries": ["[...]"],
                        },
                    },
                },
                {
                    "method": "thread/settings/updated",
                    "params": {
                        "threadSettings": {
                            "model": "gpt-6-luna",
                            "effort": "medium",
                            "serviceTier": None,
                        }
                    },
                },
            ],
        }
        context = {
            "vars": {"home": str(home), "evidence": str(evidence), "prompt": prompt},
            "providerResponse": {
                "raw": raw,
                "metadata": {
                    "codexAppServer": {"threadId": "thread", "turnId": "turn"}
                },
            },
        }
        return context

    def test_two_media_rows_require_original_native_order_and_hook_proof(self):
        for empty in [False, True]:
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as name:
                context = self.fixture(Path(name), empty)
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

    def test_missing_native_hook_or_wrong_state_cannot_claim_acceptance(self):
        with tempfile.TemporaryDirectory() as name:
            context = self.fixture(Path(name))
            context["providerResponse"]["raw"]["notifications"] = []
            self.assertFalse(
                GRADE.get_assert('{"colors":["red","blue"],"imageCount":2}', context)[
                    "pass"
                ]
            )

    def test_retained_images_hashes_state_and_audit_allow_offline_grade_after_cleanup(
        self,
    ):
        import hashlib
        import shutil

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            context = self.fixture(root)
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
