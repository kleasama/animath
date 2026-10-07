import json
import math
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from animath.core.errors import AssembleError

RATE = 48000
LUFS, CEILING_DB = -16.0, -2.5
TARGET = f"I={LUFS}:TP=-1.5:LRA=11"
MEASURED = ("input_i", "input_tp")
BITEXACT = ["-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]


@dataclass(frozen=True)
class Stream:
    codec: str
    duration_s: float
    width: int = 0
    height: int = 0
    fps: Fraction = Fraction(0)
    channels: int = 0
    rate: int = 0


def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    exe = shutil.which(args[0])
    if exe is None:
        raise AssembleError(f"{args[0]} not found on PATH")
    p = subprocess.run([exe, *args[1:]], capture_output=True, text=True, check=False)
    if p.returncode:
        raise AssembleError(f"{args[0]} exit {p.returncode}: {p.stderr.strip()[-2000:]}")
    return p


def version() -> str:
    return run(["ffmpeg", "-version"]).stdout.splitlines()[0]


def probe(path: Path, kind: str) -> Stream:
    """First stream of kind 'v' or 'a'; duration from the container."""
    keys = "codec_name,width,height,r_frame_rate,channels,sample_rate"
    out = run(
        [
            *("ffprobe", "-v", "error", "-select_streams", f"{kind}:0", "-show_entries"),
            *(f"stream={keys}:format=duration", "-of", "json", str(path)),
        ]
    ).stdout
    data = json.loads(out)
    if not data.get("streams"):
        raise AssembleError(f"{path.name}: no {kind} stream")
    s = data["streams"][0]
    return Stream(
        codec=s["codec_name"],
        duration_s=float(data["format"]["duration"]),
        width=int(s.get("width", 0)),
        height=int(s.get("height", 0)),
        fps=Fraction(s["r_frame_rate"]) if kind == "v" else Fraction(0),
        channels=int(s.get("channels", 0)),
        rate=int(s.get("sample_rate", 0)),
    )


def _audio(src: int, i: int, samples: int) -> str:
    return (
        f"[{src}:a:0]aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"apad,atrim=end_sample={samples}[a{i}]"
    )


def _video(src: int, i: int, frames: int, fps: Fraction) -> str:
    pad = frames / fps
    return (
        f"[{src}:v:0]setpts=PTS-STARTPTS,fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={float(pad)},trim=end_frame={frames},"
        f"setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v{i}]"
    )


def _inputs(paths: Sequence[Path]) -> list[str]:
    return [a for p in paths for a in ("-i", str(p))]


def loudness(audios: Sequence[Path], samples: Sequence[int]) -> dict[str, float]:
    """Integrated loudness (LUFS) and true peak (dBTP) of the concatenated, trimmed audio."""
    n = len(audios)
    graph = ";".join(_audio(i, i, s) for i, s in enumerate(samples))
    graph += ";" + "".join(f"[a{i}]" for i in range(n))
    graph += f"concat=n={n}:v=0:a=1,loudnorm={TARGET}:print_format=json[out]"
    err = run(
        [
            *("ffmpeg", "-nostdin", "-hide_banner", *_inputs(audios)),
            *("-filter_complex", graph, "-map", "[out]", "-f", "null", "-"),
        ]
    ).stderr
    stats = json.loads(err[err.rindex("{") : err.rindex("}") + 1])
    m = {k: float(stats[k]) for k in MEASURED}
    if not all(math.isfinite(v) for v in m.values()):
        raise AssembleError(f"narration is silent: {m}")
    return m


def encode(
    clips: Sequence[Path],
    audios: Sequence[Path],
    frames: Sequence[int],
    samples: Sequence[int],
    fps: Fraction,
    measured: dict[str, float],
    threads: int,
    out: Path,
) -> None:
    """Concat; gain to LUFS, peak limiter at CEILING_DB; H.264 High yuv420p CRF 18, AAC 48 kHz."""
    n = len(clips)
    gain = LUFS - measured["input_i"]
    limit = f"limit={10 ** (CEILING_DB / 20):.4f}:attack=5:release=80:level=false:latency=true"
    graph = ";".join(
        [_video(i, i, f, fps) for i, f in enumerate(frames)]
        + [_audio(n + i, i, s) for i, s in enumerate(samples)]
    )
    graph += ";" + "".join(f"[v{i}][a{i}]" for i in range(n))
    graph += f"concat=n={n}:v=1:a=1[v][c];[c]volume={gain:.2f}dB,alimiter={limit}[a]"
    run(
        [
            *("ffmpeg", "-nostdin", "-hide_banner", "-y", *_inputs(clips), *_inputs(audios)),
            *("-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-threads", str(threads)),
            *("-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "18"),
            *("-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "160k"),
            *("-ar", str(RATE), "-movflags", "+faststart", "-map_metadata", "-1", *BITEXACT),
            str(out),
        ]
    )
