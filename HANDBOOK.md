# Animath — Handbook

Reference for a developer at any pickup point.

## 1 Overview

1.1 Purpose and scope: SPEC §1.
1.2 Pipeline $\Phi$, stages $\Phi_1,\dots,\Phi_7$: SPEC §6.1.
1.3 Work packages and code exchange: SPEC §7.

## 2 Environment

2.1 Python ≥ 3.12, `uv` for environments; pins in `requirements.lock` (uv export, no hashes; kept compact for Drive storage, D6).
2.2 Commands:

| Command | Effect |
|---|---|
| `make setup` | create `.venv` from `requirements.lock`, install package editable |
| `make lock` | re-resolve pins from `pyproject.toml` |
| `make check` | (also CI on push/PR) ruff, ruff format, mypy --strict, pytest (coverage ≥ 95%), licence audit |
| `.venv/bin/animath schema <kind>` | JSON schema of an artifact kind |
| `.venv/bin/animath inspect <kind> <digest>` | print a stored artifact |
| `.venv/bin/animath config` | effective settings |

2.3 Settings (`core.config.Settings`): defaults, then TOML file (`--config`), then `ANIMATH_<FIELD>` variables. Fields: `store`, `model`, `effort`, `max_tokens`, `workers`, `offline`.
2.4 Image: `docker/Dockerfile` (TeX Live, dvisvgm, ffmpeg, pandoc, cairo/pango, espeak-ng, node, gfortran).

## 3 Data contracts and storage

3.1 Hashing. For a JSON value $x$, let $c(x)$ be its canonical encoding (UTF-8, sorted keys, no whitespace). Then
$$d(x) = \mathrm{SHA256}(c(x)). \tag{3.1}$$
Blobs are addressed by $\mathrm{SHA256}$ of their bytes.

3.2 Stage key. For stage $\sigma$ of version $v$ with input digests $d_1,\dots,d_m$,
$$k_\sigma = d\big([\sigma, v, d_1, \dots, d_m]\big). \tag{3.2}$$
A stage is skipped iff an artifact is indexed under $k_\sigma$ (SPEC Invariants 4.1).

3.3 Layout of the store root:

| Path | Content |
|---|---|
| `blobs/<d[:2]>/<d[2:]>` | raw bytes |
| `artifacts/<kind>/<d>.json` | canonical artifact JSON |
| `index/<ns>/<key>` | digest referenced by key; `ns` = artifact kind or `llm` |

3.4 Concurrency. Every write goes to a temporary file in the target directory, is fsynced, then renamed with `os.replace`; readers observe either nothing or a complete file. Content-addressed writes are idempotent; index writes are last-writer-wins. Reads verify digests.

**Algorithm 3.1 (atomic write).** `mkstemp` in target dir → write → flush → fsync → `os.replace`; on any exception unlink the temporary and re-raise.

3.5 Validation rules: SPEC Invariants 4.1(3). `depends_on` acyclicity uses Kahn's algorithm, $O(|V|+|E|)$.

## 4 LLM access

4.1 `LLM` protocol: `parse(schema, system, prompt, images) -> (instance, Usage)`.
4.2 `Claude`: `beta.messages.parse` with `output_format=schema`, ephemeral cache on the system prompt, PNG images first, `output_config.effort`, server-side refusal fallback (`fallbacks="default"`). Any `stop_reason` other than `end_turn` raises `LLMError`.
4.3 `Replay`: key $d([\text{model:effort}, \text{JSON schema}, \text{system}, \text{prompt}, [d(\text{image}_i)]])$; hit returns cached instance with zero usage; offline miss raises `LLMError`. Unit tests run offline.

## 5 Ingestion
## 6 Knowledge extraction
## 7 Storyboard
## 8 Numerics
## 9 Scenes and rendering
Algorithm 9.1 Scene generation: SPEC Algorithm 6.1.
## 10 Narration

10.1 $\Phi_6$ maps each scene $s$ with lines $\ell_1,\dots,\ell_m$ to a `Narration`. Entry: `narrate.narrate(board, store, tts, verbalizer, workers) -> {scene id: digest}`.

| Module | Content |
|---|---|
| `verbalize` | split prose and inline math (`$…$`, `$$…$$`, `\(…\)`); TeX → MathML (MathJax 3.2.1) → speech (SRE 4.1.4, ClearSpeak) in one `node sre.cjs` call per stage run |
| `tts` | `TTS` protocol (`id`, `rate`, `synth(text) -> int16 PCM`); `Kokoro`, `Espeak`; WAV I/O |
| `align` | trim, concatenate, bookmark and word times (Algorithm 10.1) |
| `subtitles` | WebVTT cues |
| `proc` | subprocess call with typed failure |

10.2 Runtime requirements: `espeak-ng` on `PATH`; `NODE_PATH` holding `speech-rule-engine@4.1.4` and `mathjax-full@3.2.1`; for Kokoro a directory with `model.onnx` (onnx-community/Kokoro-82M-v1.0-ONNX), `config.json` with key `vocab` (hexgrad/Kokoro-82M), `voices/<voice>.bin` (float32, $510\times256$).

| Backend | Rate | Input | Status |
|---|---|---|---|
| `Kokoro` (default, SPEC Q6) | 24 kHz | espeak-ng IPA → vocab ids, chunks $\le 510$, style row $\lvert\text{chunk}\rvert-1$ | tested against a fake ONNX session only: Hugging Face is unreachable from the build containers |
| `Espeak` | 22.05 kHz | text on stdin | verified |

10.3 Cache key. With $v$ the stage version,
$$k = d\big(["\text{narrate}", v, d(\text{id}, \text{narration}), \text{tts.id}, \text{verbalizer.id}]\big). \tag{10.1}$$
Edits to visuals, math or duration of a scene do not trigger re-synthesis.

**Algorithm 10.1 (timeline).** Rate $r$, gap $g = \operatorname{round}(0.3\,r)$, offset $o_1 = 0$. For each line $i$:
1. Synthesize; let $[a_i, b_i)$ be the samples between the first and last with $\lvert x\rvert > 328$ (≈ −40 dBFS); $n_i = b_i - a_i$; silence raises `NarrateError`.
2. Bookmark of $\ell_i$ at $o_i / r$.
3. Tokens $\tau_1,\dots,\tau_K$ with weights $w_k = 1 + \#\text{alnum}(\tau_k)$, $C_k = \sum_{j\le k} w_j$; token $k$ spans
$$\big[\,o_i + \operatorname{round}(n_i C_{k-1}/C_K),\; o_i + \operatorname{round}(n_i C_k/C_K)\,\big] / r. \tag{10.2}$$
4. $o_{i+1} = o_i + n_i + g$.

Output: voiced segments joined by $g$ zeros (no trailing gap); duration $= \sum_i n_i/r + (m-1)g/r$. Integer sample arithmetic guarantees the `Narration` validators (monotone words, last end $\le$ duration).

10.4 Accuracy. Bookmarks coincide with speech onset up to the threshold, so $Q_3$ at bookmark granularity holds by construction. Word times (10.2) are length-proportional estimates used only for subtitles.

10.5 Subtitles. A cue holds at most two lines of 42 columns; a new cue starts after `.?!` or a pause $> 0.25$ s. `subtitles.vtt([(narration, offset), …])` is called by the orchestrator (Rule 6.2 forbids `assemble` to import `narrate`).

10.6 Concurrency. Scenes run on a thread pool of `workers`; formulas of all uncached scenes are verbalized in one subprocess before the pool starts; the ONNX session is shared (thread-safe `run`) with `intra_op_num_threads` fixed for determinism.

10.7 Deviations from SPEC §6.3. Forced alignment (torchaudio) is not used: per-line synthesis makes bookmarks exact, torchaudio's `forced_align` is deprecated, and torch would dominate the image. espeak-ng IPA drops punctuation, so Kokoro prosody lacks pause cues.

10.8 Measurements (4 cores, Espeak, two lines with three formulas): cold 0.74 s, cached 0.22 s, including interpreter start.

## 11 Assembly
## 12 Evaluation
## 13 Performance metrics

| Item | Value |
|---|---|
| `make check` wall time (WP0) | ≈ 5 s on 4 cores |

## 14 Decisions log

| # | Date | Decision | Reason |
|---|---|---|---|
| D1 | 2026-10-07 | Code in GitHub `kleasama/animath`; Drive holds documents and checkpoint bundles | parallel WPs need a git remote |
| D2 | 2026-10-07 | C0 defaults accepted (SPEC §8) | user approval |
| D3 | 2026-10-07 | CPU-only toolchain; GPU parsers replaced by Claude vision transcription | no GPU in containers |
| D4 | 2026-10-07 | Schemas frozen at C1; changes only through integrator | parallel WPs without conflicts |
| D5 | 2026-10-07 | Commits authored by the user, no co-author trailers | user preference |
| D6 | 2026-10-07 | `requirements.lock` instead of `uv.lock` (177 kB) | Drive transfer size |
