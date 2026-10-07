import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from animath.core.errors import ConfigError
from animath.core.schemas import Model

Effort = Literal["low", "medium", "high", "xhigh", "max"]
PREFIX = "ANIMATH_"


class Settings(Model):
    store: Path = Path(".animath")
    model: str = "claude-opus-5-5"
    effort: Effort = "high"
    max_tokens: int = Field(32000, ge=1024, le=128000)
    workers: int = Field(os.cpu_count() or 1, ge=1)
    offline: bool = False


def load(path: Path | None = None, env: Mapping[str, str] = os.environ) -> Settings:
    """Settings from defaults, then TOML file, then ANIMATH_* environment variables."""
    values: dict[str, object] = {}
    if path is not None:
        try:
            values.update(tomllib.loads(path.read_text()))
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"cannot read {path}: {e}") from e
    for name in Settings.model_fields:
        if (v := env.get(PREFIX + name.upper())) is not None:
            values[name] = v
    try:
        return Settings.model_validate(values)
    except ValidationError as e:
        raise ConfigError(str(e)) from e
