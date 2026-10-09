# Animath

[![check](https://github.com/kleasama/animath/actions/workflows/check.yml/badge.svg)](https://github.com/kleasama/animath/actions/workflows/check.yml)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

Animath turns a mathematical document (Markdown, LaTeX or PDF) into a narrated, captioned, animated video.

> [!NOTE]
> Experimental. The Docker image and the Anthropic API path have not yet been run end to end.

## Contents

- [Install](#install)
- [Configure](#configure)
- [Run](#run)
- [Commands](#commands)
- [Pipeline](#pipeline)
- [Develop](#develop)
- [License](#license)

## Install

Linux (tested on Ubuntu 24.04), Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

System packages:

```sh
sudo apt-get install -y --no-install-recommends \
  build-essential ffmpeg pandoc libcairo2-dev libpango1.0-dev pkg-config \
  dvisvgm espeak-ng libosmesa6 nodejs npm \
  texlive-latex-base texlive-latex-extra texlive-fonts-recommended \
  texlive-science texlive-extra-utils
sudo npm install -g speech-rule-engine@4.1.4 mathjax-full@3.2.1
export NODE_PATH=$(npm root -g)
```

Animath:

```sh
git clone https://github.com/kleasama/animath
cd animath
make setup
```

Alternatively, `docker/Dockerfile` builds an image with the full toolchain and the voice.

## Configure

| Variable | Purpose |
|---|---|
| `ANIMATH_API_KEY` or `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANIMATH_LLM=session` | no API: each model request is written to `.animath/pending/<key>/request.json`; write `answer.json` beside it and run again |
| `ANIMATH_KOKORO` | directory with the Kokoro voice files; without it, espeak-ng speaks |

Every setting printed by `animath config` can be overridden by `ANIMATH_<NAME>` or by a TOML file passed with `--config`.

Kokoro voice files: `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the [kokoro-onnx release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0), and [`config.json`](https://github.com/thewh1teagle/kokoro-onnx/blob/main/src/kokoro_onnx/config.json).

## Run

```sh
.venv/bin/animath run tests/golden/efie/efie.md -p duration_s=180
```

The run pauses for review after the knowledge graph and after the storyboard; continue with `--approve`, or with `--edit artifact.json` to use an edited artifact. On completion it prints the manifest digest and the MP4 path. Artifacts are cached by content hash in `.animath/`, so a rerun resumes at the first stage whose input changed.

| Option | Effect |
|---|---|
| `--section 2.1` | restrict to a section (ordinals, or titles split by `/`) |
| `--pages 3-7` | restrict a PDF to these pages |
| `-p duration_s=600` | target length in seconds, at most 1800 |
| `-p audience=undergraduate` | `undergraduate`, `graduate` (default) or `expert` |
| `-p budget_usd=5` | stop once model spend exceeds this many US dollars |
| `-p approval_gates=false` | run without pausing |

## Commands

| Command | Effect |
|---|---|
| `animath run SOURCE` | source to video |
| `animath stage NAME DIGEST` | run one stage on a stored input |
| `animath eval DIGEST` | quality metrics of a finished video |
| `animath inspect KIND DIGEST` | print a stored artifact |
| `animath schema KIND` | print the JSON schema of an artifact kind |
| `animath config` | print the effective settings |

## Pipeline

| | Stage | Output |
|---|---|---|
| Φ1 | ingest | document IR |
| Φ2 | extract | knowledge graph |
| Φ3 | plan | storyboard |
| Φ4 | compute | numerical data |
| Φ5 | animate | scene clips (Manim) |
| Φ6 | narrate | speech, captions, word timings |
| Φ7 | assemble | MP4 and WebVTT subtitles |

Φ4 and Φ6 run in parallel; Φ5 renders scenes in a process pool.

## Develop

```sh
make check
```

Runs ruff, mypy `--strict`, pytest with at least 95 % line and branch coverage, and a licence audit. CI runs it on pull requests and on pushes to main.

## License

[BSD 3-Clause](LICENSE) © 2026 Klearchos Samaras
