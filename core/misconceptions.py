"""Coarse, non-overlapping misconception buckets for the class map.

Fine-grained buckets (dropped-term vs skipped-step vs wrong-operation) proved
unreliable on a reliability check: the examiner's own note rarely determines a
unique fine label, and a wrong label is worse than a coarse one. So the examiner
emits ONE of these coarse tags at decision time — where it can see the actual
equations, not just its own sentence. See CHECK_PROMPT in vision/step_checker.py.
"""

CATEGORIES = ("sign", "arithmetic", "algebra_step", "other")

LABELS = {
    "sign":         "Sign error",
    "arithmetic":   "Arithmetic slip",
    "algebra_step": "Algebra step (dropped term / skipped / wrong operation)",
    "other":        "Other",
}


def normalise(tag: str) -> str:
    """Coerce a raw tag to a known category, defaulting to 'other'."""
    tag = (tag or "").strip().lower()
    return tag if tag in CATEGORIES else "other"
