"""Stage Φ5: (Scene, DataSet, Narration) -> SceneRender (SPEC Algorithm 6.1)."""

from collections.abc import Mapping

from animath.core.errors import AnimateError
from animath.core.hashing import digest_of
from animath.core.schemas import DataSet, Narration, Params, Scene, SceneRender, Usage
from animath.core.store import Store
from animath.llm import LLM
from animath.scene.codegen import CODE, gate, registered
from animath.scene.critic import critique
from animath.scene.primitives import PRIMITIVES
from animath.scene.render import render
from animath.scene.repair import record, repair

VERSION = "1"
ANIMATE_PARAMS = {"width", "height", "fps", "max_retries"}


def check(
    s: Scene,
    data: Mapping[str, DataSet],
    narration: Narration | None,
    store: Store,
    llm: LLM,
    params: Params,
) -> tuple[list[str], Usage]:
    """Static gate, draft render, critic; first failing step's errors."""
    errors = [
        f"{s.id}.{i}:{CODE.name}: {e}"
        for i, v in enumerate(s.visuals)
        if v.primitive == CODE.name
        for e in gate(str(v.args.get("code", "")))
    ]
    if errors:
        return errors, Usage()
    try:
        draft = render(s, params, store, narration, data, draft=True)
    except AnimateError as e:
        return [str(e)], Usage()
    return critique(s, draft, store, llm)


def animate(
    scene: Scene,
    data: Mapping[str, DataSet],
    narration: Narration | None,
    store: Store,
    llm: LLM,
    params: Params,
) -> tuple[SceneRender, Usage]:
    """Algorithm 9.3 with the usage of all LLM calls; Usage() on a stage key hit. Not thread-safe;
    parallelize over processes."""
    inputs = [digest_of(data[r.digest]) if r.digest in data else None for r in scene.data]
    key = Store.key(
        "animate",
        VERSION,
        digest_of(scene),
        digest_of(
            [
                inputs,
                digest_of(narration) if narration else None,
                params.model_dump(mode="json", include=ANIMATE_PARAMS),
            ]
        ),
    )
    if (hit := store.lookup(SceneRender, key)) is not None:
        return hit, Usage()
    s, usage = scene, Usage()
    with registered():
        errors = [
            f"{s.id}.{i}:{v.primitive}: not a catalog primitive; implement it as `{CODE.name}`"
            for i, v in enumerate(s.visuals)
            if v.primitive not in PRIMITIVES
        ]
        for _ in range(params.max_retries + 1):
            if errors:
                s, bad, u = repair(s, errors, llm, store)
                usage += u
                if bad:
                    errors = [*errors, *bad]
                    continue
            errors, u = check(s, data, narration, store, llm, params)
            usage += u
            if not errors:
                out = render(s, params, store, narration, data)
                out = out.model_copy(
                    update={"checks": {**out.checks, "static": True, "critic": True}}
                )
                store.put(out, key)
                return out, usage
            record(store, s, errors)
    raise AnimateError(f"scene {scene.id}: unresolved after {params.max_retries} repairs: {errors}")
