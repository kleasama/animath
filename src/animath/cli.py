import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from animath import __version__
from animath.core import config
from animath.core.errors import AnimathError
from animath.core.schemas import ARTIFACTS
from animath.core.store import Store


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="animath")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", type=Path, help="TOML settings file")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema", help="print the JSON schema of an artifact kind")
    s.add_argument("kind", choices=sorted(ARTIFACTS))
    i = sub.add_parser("inspect", help="print a stored artifact")
    i.add_argument("kind", choices=sorted(ARTIFACTS))
    i.add_argument("digest")
    sub.add_parser("config", help="print effective settings")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = config.load(args.config)
        if args.cmd == "schema":
            out = json.dumps(ARTIFACTS[args.kind].model_json_schema(), indent=2)
        elif args.cmd == "inspect":
            out = (
                Store(settings.store)
                .get(ARTIFACTS[args.kind], args.digest)
                .model_dump_json(indent=2)
            )
        else:
            out = settings.model_dump_json(indent=2)
    except AnimathError as e:
        print(f"animath: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0
