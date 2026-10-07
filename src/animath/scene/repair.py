import json
import re

from pydantic import Field, ValidationError

from animath.core.errors import AnimateError
from animath.core.hashing import digest_of
from animath.core.schemas import Model, Scene, Usage, Visual
from animath.core.store import Store
from animath.llm import LLM
from animath.scene.codegen import CodeArgs, api
from animath.scene.layout import GRID
from animath.scene.primitives import catalog

PITFALLS = 8
W, H = 8.0 * 16 / 9, 8.0
CELLS = {
    r: (round((u1 - u0) * W, 2), round((v1 - v0) * H, 2)) for r, (u0, v0, u1, v1) in GRID.items()
}
SYSTEM = f"""You repair the visuals of one scene of an educational mathematics video (Manim CE).
1. Replace only the visuals listed under `repair`; keep what works. Fix every error and avoid the
pitfalls.
2. `args` is a JSON object valid against the schema of `primitive` in the catalog; `at` is a
bookmark or null.
3. Prefer a catalog primitive; use `code` only where no primitive shows the visual.
4. `code` defines exactly `def build(array)` returning one Mobject, using only the API below; no
imports, while, try, with, raise or names beginning with `_`. `array(data, name, part=None)`
returns the real NumPy array `name` of data request `data`; complex arrays need `part` in abs,
real, imag.
5. A visual is scaled down to fit its region (width, height in frame units):
{json.dumps(CELLS)}; below scale 0.4 the layout is rejected. Visuals alive at the same time need
disjoint regions; `main` meets `left` and `right`. `until` names the bookmark removing the visual.

Catalog: {json.dumps({**catalog(), "code": CodeArgs.model_json_schema()}, sort_keys=True)}

API:
{api()}"""


class Fix(Model):
    index: int = Field(ge=0)
    primitive: str
    args: str = Field(description="JSON object")
    at: str | None = None


class Patch(Model):
    fixes: list[Fix] = Field(min_length=1)


def indices(scene: Scene, text: str) -> list[int]:
    """Visuals named `<scene>.<i>:` in an error message."""
    n = len(scene.visuals)
    found = {int(i) for i in re.findall(rf"\b{re.escape(scene.id)}\.(\d+):", text)}
    return sorted(i for i in found if i < n)


def record(store: Store, scene: Scene, errors: list[str]) -> None:
    """Pitfall memory: last PITFALLS distinct failures per primitive (last writer wins)."""
    for e in errors:
        for name in {scene.visuals[i].primitive for i in indices(scene, e)} or {"scene"}:
            past = pitfalls(store, [name])
            new = [*(p for p in past if p != e[:300]), e[:300]][-PITFALLS:]
            store.set_ref("pitfall", Store.key(name), store.put_blob(json.dumps(new).encode()))


def pitfalls(store: Store, names: list[str]) -> list[str]:
    out: list[str] = []
    for name in sorted(set(names)):
        d = store.ref("pitfall", Store.key(name))
        out += json.loads(store.get_blob(d)) if d else []
    return out


def apply(scene: Scene, patch: Patch, allowed: list[int]) -> Scene:
    visuals = list(scene.visuals)
    for f in patch.fixes:
        if f.index not in allowed:
            raise AnimateError(
                f"scene {scene.id}: patch touches visual {f.index}, not in {allowed}"
            )
        try:
            args = json.loads(f.args)
        except json.JSONDecodeError as e:
            raise AnimateError(f"{scene.id}.{f.index}:{f.primitive}: args not JSON: {e}") from e
        if not isinstance(args, dict):
            raise AnimateError(f"{scene.id}.{f.index}:{f.primitive}: args not a JSON object")
        visuals[f.index] = Visual(primitive=f.primitive, args=args, at=f.at)
    try:
        return Scene.model_validate({**scene.model_dump(), "visuals": visuals})
    except ValidationError as e:
        raise AnimateError(f"scene {scene.id}: patched scene invalid: {e}") from e


def repair(
    scene: Scene, errors: list[str], llm: LLM, store: Store
) -> tuple[Scene, list[str], Usage]:
    """Localized repair: visuals named by the errors, else the whole scene. A rejected patch
    leaves the scene unchanged and is returned as an error."""
    allowed = sorted({i for e in errors for i in indices(scene, e)}) or list(
        range(len(scene.visuals))
    )
    task = {
        "goal": scene.goal,
        "narration": [ln.model_dump() for ln in scene.narration],
        "math": list(scene.math),
        "data": [r.model_dump() for r in scene.data],
        "visuals": [{"index": i, **v.model_dump()} for i, v in enumerate(scene.visuals)],
        "errors": errors,
        "repair": allowed,
        "pitfalls": pitfalls(store, [scene.visuals[i].primitive for i in allowed]),
    }
    key = digest_of([SYSTEM, scene.model_dump(mode="json"), errors])
    if (d := store.ref("repair", key)) is not None:
        patch, usage = Patch.model_validate_json(store.get_blob(d)), Usage()
    else:
        patch, usage = llm.parse(Patch, SYSTEM, json.dumps(task, indent=1, sort_keys=True))
        store.set_ref("repair", key, store.put_blob(patch.model_dump_json().encode()))
    try:
        return apply(scene, patch, allowed), [], usage
    except AnimateError as e:
        return scene, [str(e)], usage
