import subprocess
from collections.abc import Sequence

from animath.core.errors import NarrateError


def run(cmd: Sequence[str], data: bytes) -> bytes:
    """Stdout of `cmd` fed `data` on stdin; NarrateError on spawn failure or nonzero exit."""
    try:
        p = subprocess.run(list(cmd), input=data, capture_output=True, check=False)
    except OSError as e:
        raise NarrateError(f"cannot run {cmd[0]}: {e}") from e
    if p.returncode:
        raise NarrateError(f"{cmd[0]} exited {p.returncode}: {p.stderr.decode(errors='replace')}")
    return p.stdout
