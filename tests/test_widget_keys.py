"""Widget keys in the interface.

`_picker` on the V0 page took a fixed key and is called twice - once for the
footprint source and once for the user count - so the second call raised
StreamlitDuplicateElementKey and the page would not load.

Raising is the good outcome. The one to avoid is the version where it does
not: two widgets sharing a key share a value, so picking a footprint fact
would silently set the user-count source to the same row, and the estimate
would credit a known fact as the source of a number it never stated.
"""
import ast
from pathlib import Path


def _pages():
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "analyst_ui" / "streamlit_app").rglob("*.py"))


def test_no_function_hands_a_literal_key_to_a_widget():
    """A function is called more than once or it would not be a function, and
    a literal key inside one collides with itself the second time."""
    offenders = []
    for path in _pages():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                        offenders.append(
                            f"{path.name}::{fn.name} key={kw.value.value!r}")
    assert not offenders, offenders


def test_the_v0_picker_keys_on_its_driver():
    """The two pickers choose different things and must not share a value."""
    page = next(p for p in _pages() if p.name.startswith("6_Run_V0"))
    source = page.read_text()
    assert 'key=f"v0_choice_{driver}"' in source
    assert 'key="v0_choice"' not in source
