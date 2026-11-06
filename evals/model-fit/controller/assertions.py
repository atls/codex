"""Require production execution evidence or an explicit no-model control."""


def get_assert(output, context):
    try:
        scenario = context["vars"]["scenario"]
        observed = context["providerResponse"].get("metadata") or {}
        bypass = (
            observed.get("source_failure_simulation") is True
            if scenario.get("source_failure")
            else observed.get("user_choice_bypass") is True
            if scenario.get("prior_choice")
            else False
        )
        turns = observed.get("model_turns")
        numeric = type(turns) in (int, float)
        passed = numeric and (
            turns == 0
            if bypass
            else observed.get("skill_item_seen") is True and turns >= 1
        )
    except (KeyError, TypeError, AttributeError):
        bypass = False
        passed = False
    reason = (
        (
            "Explicit no-model control confirmed"
            if bypass
            else "Production native model turn and skill confirmed"
        )
        if passed
        else "Required controller execution evidence is absent"
    )
    return {"pass": passed, "score": 1 if passed else 0, "reason": reason}
