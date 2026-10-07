import json
from pathlib import Path

import pytest

from animath import __version__
from animath.cli import main
from animath.core.schemas import DocIR
from animath.core.store import Store


def test_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "storyboard"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["title"] == "Storyboard"
    assert "scenes" in s["required"]


def test_inspect_and_config(
    tmp_path: Path, doc: DocIR, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANIMATH_STORE", str(tmp_path))
    d = Store(tmp_path).put(doc)
    assert main(["inspect", "doc", d]) == 0
    assert DocIR.model_validate_json(capsys.readouterr().out) == doc
    assert main(["config"]) == 0
    assert json.loads(capsys.readouterr().out)["store"] == str(tmp_path)
    assert main(["inspect", "doc", "0" * 64]) == 1
    assert "missing doc" in capsys.readouterr().err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == __version__
