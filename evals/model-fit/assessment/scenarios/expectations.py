def assert_expected_decision(decision, active, case):
    if decision["decision"] not in case["expected_decisions"]:
        raise ValueError("Decision differs from the historical scenario contract")
    if (
        decision["decision"].startswith("recommend_")
        and case["allowed_recommendations"]
    ):
        target = "/".join(
            (
                decision.get(f"recommended_{key}") or active[key]
                for key in ("model", "effort")
            )
        )
        speed = decision.get("recommended_speed") or active["speed"]
        if speed != active["speed"]:
            target += f"/{speed}"
        if target not in case["allowed_recommendations"]:
            raise ValueError("Target differs from the historical scenario contract")
