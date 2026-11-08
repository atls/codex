"""The default assessor executes the installed package entrypoint."""

import unittest

from model_fit.infrastructure.adapters.codex.assessment import triage


class AssessmentCLITests(unittest.TestCase):
    def test_confirmed_choice_runs_default_assessor_without_inference(self):
        profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
        request = {
            "task": "confirmed work",
            "active_profile": profile,
            "prior_choice": {
                "user_selected": True,
                "same_work": True,
                "profile": profile,
            },
        }
        result = triage(request)
        self.assertEqual(result["decision"], "keep")
        self.assertEqual(result["active_model"], profile["model"])
