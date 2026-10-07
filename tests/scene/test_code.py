from typing import Any

import numpy as np
import pytest
from manim import Animation, Circle, Create, Indicate, Square, VGroup

from animath.core.errors import AnimateError
from animath.core.store import Store
from animath.scene.primitives import PRIMITIVES
from animath.scene.primitives.code import ANIMATIONS, MOBJECTS, Code, api, gate, run
from tests.scene.conftest import MAIN, context

OK = """def build(array):
    xs = np.linspace(0, 1, 3)
    f = lambda t: [t, t * t, 0]
    return VGroup(*[Dot(f(x), color=BLUE) for x in xs]).shift(UP)
"""
ACT = """def build(array):
    return VGroup(Square(), Circle())

def act(m, verb, parts):
    if verb == "grow":
        return Create(Line(parts[0].get_left(), parts[1].get_right()))
    if verb == "lift":
        return parts[0].animate.shift(UP)
    if verb == "bad":
        return 3
    return m[1 / 0]
"""
CODE = PRIMITIVES["code"]


def test_gate_accepts() -> None:
    assert gate(OK) == []
    assert gate(ACT) == []


@pytest.mark.parametrize(
    ("code", "match"),
    [
        ("def build(array:\n", "line 1: syntax error"),
        ("import os\ndef build(array):\n    return Dot()", "line 1: Import not allowed"),
        ("def build(array):\n    return Dot()\nx = 1", "module must be `def build(array)`"),
        ("def make(array):\n    return Dot()", "module must be `def build(array)`"),
        ("def build(a, b):\n    return Dot()", "module must be `def build(array)`"),
        ("def act(m, verb, parts):\n    return 1", "module must be `def build(array)`"),
        ("def build(array):\n    return 1\ndef build(array):\n    return 2", "module must be"),
        ("def build(array):\n    return 1\ndef act(m):\n    return 2", "module must be"),
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
    ("code", "match"),
    [
        ("def build(array):\n    import os", "Import not allowed"),
        ("def build(array):\n    x = 0\n    return Dot([1 / x, 0, 0])", "line 3: ZeroDivision"),
        ("def build(array):\n    return 3", "returned int, not a Mobject"),
        ("def build(array):\n    return array(0, 'u')", "missing"),
    ],
)
def test_run_errors(code: str, match: str) -> None:
    def array(*a: Any) -> None:
        raise AnimateError("scene s: data[0].u: missing")

    with pytest.raises(AnimateError, match=match):
        run(code, array)


def test_code_primitive_reads_dataset(store: Store) -> None:
    ctx = context(store, y=[1 + 2j, 3 - 1j])
    code = "def build(array):\n    y = array(0, 'y', 'imag')\n    return Dot([y[0], y[1], 0])"
    m = CODE.build(CODE.args(code=code), ctx, MAIN)
    assert m.get_center() == pytest.approx([2.0, -1.0, 0.0])
    with pytest.raises(AnimateError, match="complex array"):
        CODE.build(CODE.args(code=code.replace(", 'imag'", "")), ctx, MAIN)


def test_snippet_verbs(store: Store) -> None:
    a = CODE.args(code=ACT)
    m = CODE.build(a, context(store), MAIN)
    assert isinstance(CODE, Code)
    assert CODE.knows(m, "anything")
    assert not CODE.knows(CODE.build(CODE.args(code=OK), context(store), MAIN), "grow")
    grow = CODE.act(m, a, "grow", ["0", "1"])
    assert isinstance(grow, Create)
    assert grow.mobject.get_start() == pytest.approx(m[0].get_left())
    lift = CODE.act(m, a, "lift", ["1"])
    assert isinstance(lift, Animation)
    lift.begin()
    lift.finish()
    assert m[1].get_center() == pytest.approx([0.0, 1.0, 0.0])
    with pytest.raises(AnimateError, match=r"act\('bad'\) returned int, not an Animation"):
        CODE.act(m, a, "bad", [])
    with pytest.raises(AnimateError, match=r"line 11: ZeroDivisionError"):
        CODE.act(m, a, "other", [])
    with pytest.raises(AnimateError, match="no part '2'"):
        CODE.act(m, a, "lift", ["2"])


def test_api_pins_whitelist() -> None:
    text = api()
    assert text.count("\n") == len(MOBJECTS) + len(ANIMATIONS) + 2
    assert "Circle(radius, color)" in text
    assert "DoubleArrow(*args)" in text
    assert "Indicate(mobject, scale_factor, color" in text
    assert isinstance(run("def build(array):\n    return Circle()", lambda *a: None), Circle)
    m = run("def build(array):\n    return Square()", lambda *a: None)
    assert isinstance(m, Square)
    assert isinstance(Indicate(m), Animation)
