CATEGORIES = ('sign', 'arithmetic', 'algebra_step', 'other')
LABELS = {'sign': 'Sign error', 'arithmetic': 'Arithmetic slip', 'algebra_step': 'Algebra step (dropped term / skipped / wrong operation)', 'other': 'Other'}

def normalise(tag: str) -> str:
    tag = (tag or '').strip().lower()
    return tag if tag in CATEGORIES else 'other'