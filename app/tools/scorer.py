from app.constants import (
    DEFAULT_MATERIALITY_WEIGHT,
    MATERIALITY_WEIGHTS,
    MAX_DEDUCTION_PER_FINDING,
)


def compute_score(risk_indicators: list[dict] | None, has_report: bool = True) -> dict:
    """Compute a true green score from a list of risk indicators.

    Pure deterministic function — no async, no LLM, no HTTP.
    When no official report exists (has_report=False), base score starts at 70
    since we cannot verify any sustainability claims.
    """
    if risk_indicators is None:
        return {
            "true_green_score": None,
            "contradiction_count": 0,
            "score_breakdown": {"base_score": 100, "deductions": []},
        }

    base_score = 100.0 if has_report else 70.0

    deductions = []
    for indicator in risk_indicators:
        confidence_score: float = indicator.get("confidence_score", 0.0)
        category = indicator.get("gri_category") or indicator.get("tcfd_pillar") or "Unknown"
        materiality_weight = MATERIALITY_WEIGHTS.get(category, DEFAULT_MATERIALITY_WEIGHT)
        amount = confidence_score * materiality_weight * MAX_DEDUCTION_PER_FINDING
        deductions.append({"reason": category, "amount": amount})

    total_deduction = sum(d["amount"] for d in deductions)
    final_score = max(0.0, min(100.0, base_score - total_deduction))

    return {
        "true_green_score": final_score,
        "contradiction_count": len(risk_indicators),
        "score_breakdown": {"base_score": base_score, "deductions": deductions},
    }
