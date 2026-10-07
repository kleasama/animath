from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from animath.core.hashing import digest_of
from animath.core.schemas import Line, Narration, Scene, Storyboard
from animath.core.store import Store
from animath.narrate.align import captions, timeline
from animath.narrate.g2p import split
from animath.narrate.tts import TTS, to_wav
from animath.narrate.verbalize import Verbalizer

VERSION = "3"


def key(scene: Scene, tts: TTS, verbalizer: Verbalizer) -> str:
    return Store.key(
        "narrate",
        VERSION,
        digest_of(scene.model_dump(mode="json", include={"id", "narration"})),
        tts.id,
        verbalizer.id,
    )


def sentences(lines: Sequence[Line], said: Sequence[str]) -> list[tuple[str, dict[str, int]]]:
    """Lines joined until one ends in . ! or ?; bookmark -> index of its line's first word."""
    out: list[tuple[str, dict[str, int]]] = []
    words: list[str] = []
    cues: dict[str, int] = {}
    for ln, text in zip(lines, said, strict=True):
        if ln.bookmark:
            cues[ln.bookmark] = len(words)
        words += text.split()
        if words and any(c in ".!?" for c in split(words[-1])[2]):
            out.append((" ".join(words), cues))
            words, cues = [], {}
    if words:
        out.append((" ".join(words), cues))
    return out


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
    toks = iter(verbalizer.tokens([ln.text for s in todo for ln in s.narration]))
    texts = [[next(toks) for _ in s.narration] for s in todo]

    def one(scene: Scene, lines: list[list[tuple[str, str]]]) -> str:
        said = [" ".join(" ".join(s for _, s in t).split()) for t in lines]
        utts = [(t, c, *tts.synth(t)) for t, c in sentences(scene.narration, said)]
        audio, words, marks = timeline(utts, tts.rate)
        n = Narration(
            scene_id=scene.id,
            audio=store.put_blob(to_wav(audio, tts.rate)),
            duration_s=audio.size / tts.rate,
            words=tuple(words),
            captions=tuple(captions([x for t in lines for x in t], words)),
            bookmarks=marks,
        )
        return store.put(n, keys[scene.id])

    with ThreadPoolExecutor(workers) as ex:
        done.update(zip([s.id for s in todo], ex.map(one, todo, texts), strict=True))
    return {s.id: done[s.id] for s in board.scenes}
