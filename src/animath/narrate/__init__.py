"""Stage Φ6: Storyboard -> Narration per scene."""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from animath.core.hashing import digest_of
from animath.core.schemas import Line, Narration, Scene, Storyboard
from animath.core.store import Store
from animath.narrate.align import captions, timeline
from animath.narrate.g2p import split
from animath.narrate.tts import TTS, to_wav
from animath.narrate.verbalize import Verbalizer

VERSION = "4"


def key(scene: Scene, tts: TTS, verbalizer: Verbalizer, speed: float) -> str:
    return Store.key(
        "narrate",
        VERSION,
        digest_of(scene.model_dump(mode="json", include={"id", "narration"})),
        tts.id,
        verbalizer.id,
        f"{speed:.2f}",
    )


def sentences(
    lines: Sequence[Line], said: Sequence[str]
) -> list[tuple[str, dict[str, int], float]]:
    """Lines joined until one ends in . ! or ? or pauses, with that line's pause.

    Bookmark -> index of its line's first word in the utterance.
    """
    out: list[tuple[str, dict[str, int], float]] = []
    words: list[str] = []
    cues: dict[str, int] = {}
    for ln, text in zip(lines, said, strict=True):
        if ln.bookmark:
            cues[ln.bookmark] = len(words)
        words += text.split()
        if words and (ln.pause_s or any(c in ".!?" for c in split(words[-1])[2])):
            out.append((" ".join(words), cues, ln.pause_s))
            words, cues = [], {}
    if words:
        out.append((" ".join(words), cues, 0.0))
    return out


def narrate(
    board: Storyboard, store: Store, tts: TTS, verbalizer: Verbalizer, workers: int = 1
) -> dict[str, str]:
    """Φ6: Narration digest per scene id, in storyboard order; cached scenes skip synthesis.

    One speed for the storyboard brings its spoken words to `tts.wpm`.
    """
    toks = iter(verbalizer.tokens([ln.text for s in board.scenes for ln in s.narration]))
    texts = {s.id: [next(toks) for _ in s.narration] for s in board.scenes}
    said = {k: [" ".join(" ".join(x for _, x in t).split()) for t in v] for k, v in texts.items()}
    sents = {s.id: sentences(s.narration, said[s.id]) for s in board.scenes}
    flat = [t for ss in sents.values() for t, _, _ in ss]
    n = max(1, sum(len(t.split()) for t in flat))
    with ThreadPoolExecutor(workers) as ex:
        speed = round(sum(ex.map(tts.natural, flat)) * tts.wpm / (60 * n), 2)
        keys = {s.id: key(s, tts, verbalizer, speed) for s in board.scenes}
        done = {}
        for sid, k in keys.items():
            if (hit := store.lookup(Narration, k)) is not None:
                done[sid] = digest_of(hit)

        def one(scene: Scene) -> str:
            utts = [(t, c, p, *tts.synth(t, speed)) for t, c, p in sents[scene.id]]
            audio, words, marks = timeline(utts, tts.rate)
            nar = Narration(
                scene_id=scene.id,
                audio=store.put_blob(to_wav(audio, tts.rate)),
                duration_s=audio.size / tts.rate,
                words=tuple(words),
                captions=tuple(captions([x for t in texts[scene.id] for x in t], words)),
                bookmarks=marks,
            )
            return store.put(nar, keys[scene.id])

        todo = [s for s in board.scenes if s.id not in done]
        done.update(zip([s.id for s in todo], ex.map(one, todo), strict=True))
    return {s.id: done[s.id] for s in board.scenes}
