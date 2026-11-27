import unittest

from vector_prime.application.assessment.lifecycle import assess


class AvailableProfiles:
    def supported(self, profile):
        return True


class WorkContinuityTests(unittest.TestCase):
    active = {"model": "fixture-current", "effort": "high", "speed": None}

    def proposal(self, relation, decision="recommend_lighter"):
        return {
            "active_model": self.active["model"],
            "active_effort": self.active["effort"],
            "active_speed": self.active["speed"],
            "decision": decision,
            "recommended_model": "fixture-alternative",
            "recommended_effort": "low",
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "A profile must fit the required work.",
            "task_inference": "A different profile was proposed.",
            "reason": "Fixture proposal to exercise the continuity boundary.",
            "work_relation": relation,
        }

    def evaluate(self, output, diagnostics=None):
        return assess(
            {
                "task": "Explain the omission in your previous result.",
                "active_profile": self.active,
                "context": "The previous response completed the requested work.",
            },
            "fixture-evaluator",
            "low",
            1,
            diagnostics=diagnostics,
            source_reader=lambda: ("Fixture guidance", AvailableProfiles()),
            evaluator=lambda *args: output,
        )

    def test_discussion_retains_model_and_effort_despite_a_valid_proposal(self):
        for decision in ("recommend_lighter", "recommend_stronger"):
            with self.subTest(decision=decision):
                result = self.evaluate(self.proposal("discussion", decision))
                self.assertEqual(result["decision"], "keep")
                self.assertEqual(
                    {field: result[f"active_{field}"] for field in self.active},
                    self.active,
                )
                for field in self.active:
                    self.assertIsNone(result[f"recommended_{field}"])
                self.assertNotIn("work_relation", result)

    def test_execution_and_explicit_reselection_can_change_profile(self):
        for relation in ("execution", "explicit_reselection"):
            with self.subTest(relation=relation):
                result = self.evaluate(self.proposal(relation))
                self.assertEqual(result["decision"], "recommend_lighter")
                self.assertEqual(result["recommended_model"], "fixture-alternative")
                self.assertEqual(result["recommended_effort"], "low")

    def test_uncertain_relation_does_not_authorize_switching(self):
        result = self.evaluate(self.proposal("uncertain"))
        self.assertEqual(result["decision"], "unknown")
        self.assertIsNone(result["recommended_model"])
        self.assertIsNone(result["recommended_effort"])

    def test_missing_relation_cannot_silently_become_a_new_task(self):
        output = self.proposal("execution")
        del output["work_relation"]
        with self.assertRaises(ValueError):
            self.evaluate(output)

    def test_diagnostics_distinguish_continuity_from_evaluator_decision(self):
        for relation, origin in (
            ("discussion", "discussion_rule"),
            ("execution", "evaluator"),
            ("explicit_reselection", "evaluator"),
            ("uncertain", "uncertain_relation"),
        ):
            with self.subTest(relation=relation):
                diagnostics = {}
                self.evaluate(self.proposal(relation), diagnostics)
                self.assertEqual(diagnostics["decision_origin"], origin)
                self.assertEqual(diagnostics["work_relation"], relation)

    def test_user_choice_has_a_distinct_origin_without_evaluator_execution(self):
        diagnostics = {}
        result = assess(
            {
                "task": "Continue the agreed work",
                "active_profile": self.active,
                "prior_choice": {
                    "user_selected": True,
                    "same_work": True,
                    "profile": self.active,
                },
            },
            "fixture-evaluator",
            "low",
            1,
            diagnostics=diagnostics,
            source_reader=lambda: self.fail("Unexpected source lookup"),
            evaluator=lambda *args: self.fail("Unexpected inference"),
        )
        self.assertEqual(result["decision"], "keep")
        self.assertEqual(diagnostics["decision_origin"], "user_choice")
        self.assertNotIn("work_relation", diagnostics)
