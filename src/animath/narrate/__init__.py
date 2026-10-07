from concurrent.futures import ThreadPoolExecutor

from animath.core.hashing import digest_of
from animath.core.schemas import Narration, Scene, Storyboard
from animath.core.store import Store
from animath.narrate.align import timeline
from animath.narrate.tts import TTS, to_wav
from animath.narrate.verbalize import Verbalizer

VERSION = "1"


def key(scene: Scene, tts: TTS, verbalizer: Verbalizer) -> str:
    return Store.key(
        "narrate",
        VERSION,
        digest_of(scene.model_dump(mode="json", include={"id", "narration"})),
        tts.id,
        verbalizer.id,
    )


def narrate(
    board: Storyboard, store: Store, tts: TTS, verbalizer: Verbalizer, workers: int = 1
) -> dict[str, str]:
    """Phi_6: Narration digest per scene id, in storyboard order; cached scenes are skipped."""
    keys = {s.id: key(s, tts, verbalizer) for s in board.scenes}
    done = {}
    for sid, k in keys.items():
        if (n := store.lookup(Narration, k)) is not None:
            done[sid] = digest_of(n)
    todo = [s for s in board.scenes if s.id not in done]
    spoken = iter(verbalizer.lines([ln.text for s in todo for ln in s.narration]))
    texts = [[next(spoken) for _ in s.narration] for s in todo]

    def one(scene: Scene, said: list[str]) -> str:
        lines = [
            (t, ln.bookmark, tts.synth(t)) for t, ln in zip(said, scene.narration, strict=True)
        ]
        audio, words, marks = timeline(lines, tts.rate)
        n = Narration(
            scene_id=scene.id,
            audio=store.put_blob(to_wav(audio, tts.rate)),
            duration_s=audio.size / tts.rate,
            words=tuple(words),
            bookmarks=marks,
        )
        return store.put(n, keys[scene.id])

    with ThreadPoolExecutor(workers) as ex:
        done.update(zip([s.id for s in todo], ex.map(one, todo, texts), strict=True))
    return {s.id: done[s.id] for s in board.scenes}
