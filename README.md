# Animath

[![check](https://github.com/kleasama/animath/actions/workflows/check.yml/badge.svg)](https://github.com/kleasama/animath/actions/workflows/check.yml)
![python](https://img.shields.io/badge/python-3.12%2B-blue)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-green)](LICENSE)

Animath turns a mathematical document (Markdown, LaTeX or PDF) into a narrated educational video: animated formulas, derivations, matrices, plots and live numerical demonstrations, with captions. It is built for high-performance numerical computing (integral equations, Krylov solvers, hierarchical matrices) but accepts any mathematical text.

```
animath run notes.tex --section 2.1 -p duration_s=300
→ video.mp4  subs.vtt  manifest.json
```

## How it works

| Stage | Map | Module |
|---|---|---|
| $\Phi_1$ Ingest | source $\to$ document IR $\mathcal{D}$ | `ingest` |
| $\Phi_2$ Extract | $\mathcal{D} \to$ knowledge graph $\mathcal{K}$ | `extract` |
| $\Phi_3$ Plan | $\mathcal{K} \to$ storyboard $\mathcal{B}$ | `plan` |
| $\Phi_4$ Compute | data requests $\to$ arrays | `numerics` |
| $\Phi_6$ Narrate | $\mathcal{B} \to$ speech, captions, word times | `narrate` |
| $\Phi_5$ Animate | scenes $\to$ Manim clips | `scene` |
| $\Phi_7$ Assemble | clips, speech $\to$ MP4 | `assemble` |

Every artifact is content-addressed, so an interrupted or edited run resumes from the first stage whose input changed. Claude reads the document, plans the storyboard and reviews the rendered frames. Every formula on screen must trace to the source.

## Install

Linux (tested on Ubuntu 24.04), Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/).

```sh
sudo apt-get install -y --no-install-recommends ffmpeg pandoc libcairo2-dev libpango1.0-dev \
  pkg-config dvisvgm espeak-ng libosmesa6 texlive-latex-base texlive-latex-extra \
  texlive-fonts-recommended texlive-science texlive-extra-utils nodejs npm
sudo npm install -g speech-rule-engine@4.1.4 mathjax-full@3.2.1
export NODE_PATH=$(npm root -g)

git clone https://github.com/kleasama/animath && cd animath
make setup        # .venv from requirements.lock
make check        # lint, types, tests
```

`docker/Dockerfile` bundles the same toolchain, including the voice below.

**Voice.** For a natural voice, download Kokoro v1.0 (`kokoro-v1.0.onnx`, `voices-v1.0.bin` from the [kokoro-onnx release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0), and its `config.json`) into a directory and set `ANIMATH_KOKORO` to it. Without it, espeak-ng speaks.

**Model.** Set `ANIMATH_API_KEY` (or `ANTHROPIC_API_KEY`) to an Anthropic API key. Alternatively, `ANIMATH_LLM=session` writes each model request to `<store>/pending/<key>/request.json` and stops. You (or a coding agent) write `answer.json` next to it and run again.

## Use

```sh
.venv/bin/animath run tests/golden/efie/efie.md -p duration_s=180
```

| Option | Effect |
|---|---|
| `--section 2.1`, `--pages 3-7` | restrict to a section, or to pages of a PDF |
| `-p duration_s=600` | target length in seconds (≤ 1800) |
| `-p audience=undergraduate` | `undergraduate`, `graduate` (default) or `expert` |
| `-p budget_usd=5` | stop once model spend exceeds this many US dollars |
| `-p approval_gates=false` | run straight through, without pausing after the knowledge graph and storyboard |
| `--approve`, `--edit artifact.json` | continue from a gate, as is or with your edited artifact |

`animath --help` lists the other commands: `config`, `schema`, `inspect`, `stage` (one stage on a stored input) and `eval` (quality metrics of a finished video).

## Documentation

| Document | Content |
|---|---|
| [`SPEC.md`](SPEC.md) | requirements, contracts, architecture |
| [`HANDBOOK.md`](HANDBOOK.md) | developer reference: algorithms, data structures, decisions, measurements |
| [`PROGRESS.md`](PROGRESS.md) | checklist, release notes, open questions, known bugs |

## Contributing

Fork, branch and open a pull request. `make check` must pass: ruff, mypy `--strict`, pytest with ≥ 95% line and branch coverage, and a licence audit. The HANDBOOK explains each module's contract before you change it.

## License

[BSD 3-Clause](LICENSE) © 2026 Klearchos Samaras
