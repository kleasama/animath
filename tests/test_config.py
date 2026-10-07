from pathlib import Path

import pytest

from animath.core import config
from animath.core.errors import ConfigError


def test_precedence_defaults_file_env(tmp_path: Path) -> None:
    assert config.load(env={}).model == "claude-opus-5-5"
    f = tmp_path / "a.toml"
    f.write_text('effort = "medium"\nworkers = 2\nstore = "/data"\n')
    s = config.load(f, env={"ANIMATH_WORKERS": "8", "ANIMATH_OFFLINE": "true"})
    assert (s.effort, s.workers, s.store, s.offline) == ("medium", 8, Path("/data"), True)


@pytest.mark.parametrize(
    ("text", "env", "match"),
    [
        ("", {"ANIMATH_EFFORT": "extreme"}, "effort"),
        ("", {"ANIMATH_WORKERS": "0"}, "workers"),
        ("max_tokens = 10", {}, "max_tokens"),
        ("bogus = 1", {}, "bogus"),
        ("effort = ", {}, "cannot read"),
    ],
)
def test_invalid_settings(tmp_path: Path, text: str, env: dict[str, str], match: str) -> None:
    f = tmp_path / "a.toml"
    f.write_text(text)
    with pytest.raises(ConfigError, match=match):
        config.load(f, env=env)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        config.load(tmp_path / "none.toml", env={})
