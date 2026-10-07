from typing import Any

import numpy as np
import pytest
from manim import Circle, VGroup

from animath.core.errors import AnimateError
from animath.core.store import Store
from animath.scene.codegen import CODE, MOBJECTS, api, gate, registered, run
from animath.scene.primitives import PRIMITIVES
from tests.scene.conftest import MAIN, context

OK = """def build(array):
    xs = np.linspace(0, 1, 3)
    f = lambda t: [t, t * t, 0]
    return VGroup(*[Dot(f(x), color=BLUE) for x in xs]).shift(UP)
"""


def test_gate_accepts() -> None:
    assert gate(OK) == []


@pytest.mark.parametrize(
    ("code", "match"),
    [
        ("def build(array:\n", "line 1: syntax error"),
        ("import os\ndef build(array):\n    return Dot()", "line 1: Import not allowed"),
        ("def build(array):\n    return Dot()\nx = 1", "exactly `def build(array)"),
        ("def make(array):\n    return Dot()", "exactly `def build(array)"),
        ("def build(a, b):\n    return Dot()", "exactly `def build(array)"),
        ("def build(array):\n    return open('f')", "line 2: name 'open' not allowed"),
        ("def build(array):\n    return Dot().__class__", "attribute '__class__' not allowed"),
        ("def build(array):\n    return '{}'.format(1)", "attribute 'format' not allowed"),
        ("def build(array):\n    np.fromfile('f')", "line 2: np only as np.<name>"),
        ("def build(array):\n    n = np\n    return n.load('f')", "line 2: np only as np.<name>"),
        ("def build(array):\n    np = 1", "line 2: np only as np.<name>"),
        ("def build(array):\n    return (x for x in ()).gi_frame", "attribute 'gi_frame'"),
        ("def build(array):\n    while 1:\n        pass", "line 2: While not allowed"),
        ("def build(array):\n    global g", "Global not allowed"),
    ],
)
def test_gate_rejects(code: str, match: str) -> None:
    assert any(match in e for e in gate(code)), gate(code)


def test_run_builds_with_data() -> None:
    m = run(OK, lambda *a: None)
    assert isinstance(m, VGroup)
    assert len(m) == 3
    assert m[2].get_center() == pytest.approx([1.0, 2.0, 0.0])
    code = "def build(array):\n    y = array(0, 'y')\n    return Dot([y[0], y[1], 0])"
    seen: list[tuple[Any, ...]] = []

    def array(*a: Any) -> Any:
        seen.append(a)
        return np.array([2.0, -1.0])

    dot = run(code, array)
    assert seen == [(0, "y")]
    assert dot.get_center() == pytest.approx([2.0, -1.0, 0.0])


@pytest.mark.parametrize(
    ("code", "exc", "match"),
    [
        ("def build(array):\n    import os", ValueError, "Import not allowed"),
        (
            "def build(array):\n    x = 0\n    return Dot([1 / x, 0, 0])",
            RuntimeError,
            "line 3: Zero",
        ),
        ("def build(array):\n    return 3", TypeError, "returned int, not a Mobject"),
        ("def build(array):\n    return array(0, 'u')", AnimateError, "missing"),
    ],
)
def test_run_errors(code: str, exc: type[Exception], match: str) -> None:
    def array(*a: Any) -> None:
        raise AnimateError("scene s: data[0].u: missing")

    with pytest.raises(exc, match=match):
        run(code, array)


def test_code_primitive_reads_dataset(store: Store) -> None:
    ctx = context(store, y=[1 + 2j, 3 - 1j])
    code = "def build(array):\n    y = array(0, 'y', 'imag')\n    return Dot([y[0], y[1], 0])"
    m = CODE.build(CODE.args(code=code), ctx, MAIN)
    assert m.get_center() == pytest.approx([2.0, -1.0, 0.0])
    with pytest.raises(AnimateError, match="complex array"):
        CODE.build(CODE.args(code=code.replace(", 'imag'", "")), ctx, MAIN)


def test_registered() -> None:
    assert "code" not in PRIMITIVES
    with registered():
        assert PRIMITIVES["code"] is CODE

    def fail() -> None:
        with registered():
            raise KeyError

    with pytest.raises(KeyError):
        fail()
    assert "code" not in PRIMITIVES


def test_api_pins_whitelist() -> None:
    text = api()
    assert text.count("\n") == len(MOBJECTS) + 2
    assert "Circle(radius, color)" in text
    assert "DoubleArrow(*args)" in text
    assert isinstance(run("def build(array):\n    return Circle()", lambda *a: None), Circle)
