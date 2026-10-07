import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from animath import __version__, pipeline
from animath.core import config
from animath.core.config import Settings
from animath.core.errors import AnimathError, ConfigError
from animath.core.hashing import digest_of
from animath.core.schemas import (
    ARTIFACTS,
    DocIR,
    KnowledgeGraph,
    Params,
    SourceBundle,
    Storyboard,
)
from animath.core.store import Store
from animath.eval import evaluate, metrics
from animath.llm import PendingError, from_settings, pending


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
    r = sub.add_parser("run", help="source to video; pauses at approval gates")
    r.add_argument("source", type=Path)
    r.add_argument("--pages", help="PDF pages, e.g. 3-7,9")
    r.add_argument("--section", help="section path: titles split by '/', or ordinals 2.3.1")
    r.add_argument("--approve", action="store_true", help="approve the pending gate as is")
    r.add_argument("--edit", type=Path, help="approve the pending gate with this artifact JSON")
    t = sub.add_parser("stage", help="run one stage on a stored input artifact")
    t.add_argument("name", choices=pipeline.STAGES)
    t.add_argument("digest", help="input: source, doc, graph, or storyboard digest")
    for x in (r, t):
        x.add_argument("-p", "--param", action="append", default=[], metavar="KEY=VALUE")
    e = sub.add_parser("eval", help="quality metrics of a manifest (SPEC §5)")
    e.add_argument("digest")
    e.add_argument("--expected", type=Path, help="reference DocIR JSON for Q2")
    e.add_argument("--judge", action="store_true", help="LLM rubric Q7")
    return p


def _params(pairs: Sequence[str]) -> Params:
    try:
        return Params.model_validate(dict(kv.split("=", 1) for kv in pairs))
    except (ValueError, ValidationError) as err:
        raise ConfigError(f"invalid parameters {list(pairs)}: {err}") from err


def _run(args: argparse.Namespace, s: Settings) -> object:
    pipe = pipeline.Pipeline(s)
    b = pipeline.bundle(args.source, _params(args.param), pipe.store, args.pages)
    edit = args.edit.read_text() if args.edit else ("" if args.approve else None)
    out = pipe.run(b, edit, args.section)
    if isinstance(out, pipeline.Paused):
        return {"source": digest_of(b), "paused": out.gate, "digest": out.digest}
    return {"manifest": digest_of(out), "video": str(pipe.store.blob_path(out.video))}


def _stage(args: argparse.Namespace, s: Settings) -> object:
    pipe, name, d, p = pipeline.Pipeline(s), args.name, args.digest, _params(args.param)
    get = pipe.store.get
    if name == "ingest":
        return digest_of(pipe.ingest(get(SourceBundle, d)))
    if name == "extract":
        return digest_of(pipe.extract(get(DocIR, d), p))
    if name == "plan":
        return digest_of(pipe.plan(get(KnowledgeGraph, d), p))
    board = get(Storyboard, d)
    data = pipe.compute(board)
    if name == "compute":
        return {k: digest_of(v) for k, v in data.items()}
    narrations = pipe.narrate(board, p)
    if name == "narrate":
        return {k: digest_of(v) for k, v in narrations.items()}
    renders = pipe.animate(board, p, data, narrations)
    if name == "animate":
        return {k: digest_of(v) for k, v in renders.items()}
    return digest_of(pipe.assemble(board, renders, narrations))


def _eval(args: argparse.Namespace, s: Settings) -> object:
    store = Store(s.store)
    try:
        exp = DocIR.model_validate_json(args.expected.read_text()) if args.expected else None
    except (OSError, ValidationError) as err:
        raise ConfigError(f"cannot read {args.expected}: {err}") from err
    m = evaluate(store, args.digest, exp, from_settings(s, store) if args.judge else None)
    return {"metrics": m, "failures": metrics.failures(m)}


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
        elif args.cmd == "config":
            out = settings.model_dump_json(indent=2)
        else:
            cmd = {"run": _run, "stage": _stage, "eval": _eval}[args.cmd]
            out = json.dumps(cmd(args, settings), indent=2)
    except PendingError:
        out = json.dumps(
            {"pending": [str(p) for p in pending(settings.store / "pending")]}, indent=2
        )
    except AnimathError as e:
        print(f"animath: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0
