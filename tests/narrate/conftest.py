import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from animath.narrate.tts import PCM

Script = Callable[[str], str]


@pytest.fixture
def script(tmp_path: Path) -> Script:
    """Executable Python script with the given body; returns its path."""

    def make(body: str) -> str:
        path = tmp_path / f"cmd{len(list(tmp_path.glob('cmd*')))}"
        path.write_text(f"#!{sys.executable}\nimport sys, json\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return os.fspath(path)

    return make


def tone(n: int, lead: int = 0, tail: int = 0, amp: int = 8000) -> PCM:
    """n voiced samples between `lead` and `tail` zeros."""
    body = (amp * np.sin(0.3 * np.arange(1, n + 1))).astype(np.int16)
    body[0] = body[-1] = amp
    return np.concatenate([np.zeros(lead, np.int16), body, np.zeros(tail, np.int16)])
