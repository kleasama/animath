# Animath — Specification v0.2

Status: approved at C0 (2026-10-07), revised for feasibility at C1. Notation: $\mathcal{S}$ source, $\mathcal{D}$ document IR, $\mathcal{K}$ knowledge graph, $\mathcal{B}$ storyboard, $\mathcal{V}$ video.

## 1 Scope

**Definition 1.1.** Animath is the map
$$\Phi : (\mathcal{S}, \pi) \mapsto \mathcal{V},$$
composed of stages $\Phi_1,\dots,\Phi_7$ over the DAG of §6.1, where $\mathcal{S}$ is a mathematical source, $\pi$ a set of user parameters, and $\mathcal{V}$ an MP4 of duration $T \le T_{\max}$.

**Input.** $\mathcal{S} \in \{\text{MD}, \text{LaTeX (single or multi-file)}, \text{PDF}\}$; content type $\in$ {formulation, textbook chapter, paper, algorithm}.

**Parameters $\pi$** (`core.schemas.Params`). target duration $T$ (default 180 s, $T_{\max}=1200$ s), audience level $\in$ {undergraduate, graduate, expert}, focus (section/equation/algorithm selector), language (default en), voice, resolution (default 1920×1080, 60 fps), style preset, seed, retry bound $N_{\text{retry}}$, budget cap, approval gates (default on).

**Output.** $\mathcal{V}$ = {`video.mp4` (H.264, AAC, faststart), `subs.vtt`, `manifest.json` (provenance, hashes, timings, usage, metrics)}.

**Out of scope (v1).** interactive output, live streaming, handwriting OCR, non-English narration, multi-hour lectures, GPU-only tooling.

## 2 Functional requirements

| ID | Requirement |
|---|---|
| F1 | Ingest MD, LaTeX, PDF into a single document IR $\mathcal{D}$ preserving sections, equations (LaTeX), theorems, proofs, algorithms, figures, citations. |
| F2 | Expand user macros; resolve `\input`/`\include`; resolve labels and references. |
| F3 | Extract $\mathcal{K}$: concepts, symbols with meaning, equations, dependency edges, key results. |
| F4 | Select a teachable subgraph of $\mathcal{K}$ fitting $T$ and audience level. |
| F5 | Produce $\mathcal{B}$: ordered scenes, each with goal, narration text, visual specification, on-screen math, duration. |
| F6 | Compile each scene to an executable animation program from a vetted primitive library; free-form code only as fallback. |
| F7 | Compute numerical data for demonstrations (e.g. convergence, spectra, fields) via the numerics module; cache by content hash. |
| F8 | Render scenes headless; verify each scene (static checks, render success, visual check of sampled frames); repair or regenerate on failure, bounded by $N_{\text{retry}}$. |
| F9 | Synthesize narration; align narration and animation at sentence/bookmark granularity; emit subtitles. |
| F10 | Assemble scenes, audio, and subtitles into $\mathcal{V}$; normalize loudness. |
| F11 | Every stage is independently runnable from its persisted input artifact (resume, re-run, override). |
| F12 | Human-in-the-loop: optional approval gates after $\mathcal{K}$ and $\mathcal{B}$; user edits to $\mathcal{B}$ are respected downstream. |
| F13 | CLI with commands `run`, `stage`, `inspect`, `schema`, `config`; Python API mirroring the CLI. |

## 3 Non-functional requirements

| ID | Requirement | Metric |
|---|---|---|
| N1 | Mathematical correctness | 0 equation transcription errors on golden set; every on-screen formula traceable to $\mathcal{D}$ or verified derivation. |
| N2 | Determinism | Pinned image, seed, thread counts and cache ⇒ frame SSIM $\ge 0.999$ across runs; LLM outputs pinned by replay cache. |
| N3 | Performance | Render throughput reported per scene; numerics vectorized/compiled; parallel scene rendering over $p$ workers; end-to-end $\le$ 30 min for $T=180$ s on 4 CPU cores (target). |
| N4 | Reliability | Typed errors per stage; no silent fallbacks; retries bounded and logged. |
| N5 | Thread/process safety | Stages pure w.r.t. inputs; workers share no mutable state; atomic artifact writes. |
| N6 | Modularity | Each stage behind a protocol; backends swappable (LLM, TTS, renderer, parser). |
| N7 | Testability | $\ge 95\%$ branch-aware line coverage; golden-set regression; no network in unit tests. |
| N8 | Reproducible environment | `requirements.lock` (exact pins); container image with TeX, ffmpeg, renderer. |
| N9 | Cost control | Token and TTS usage logged in manifest; budget cap in $\pi$. |
| N10 | Licensing | Linked dependencies permissive (audited by `make licenses`); GPL tools (pandoc, gmsh, x264) only as subprocesses; non-commercial model weights excluded. |
| N11 | CPU only | Every stage runs without a GPU. |

## 4 Data contracts

All artifacts are frozen Pydantic models (`core.schemas`), serialized as canonical JSON (sorted keys) and addressed by SHA-256; binary payloads are blobs referenced by digest.

| Artifact | Producer | Consumer | Key fields |
|---|---|---|---|
| `SourceBundle` | user | $\Phi_1$ | format, entry, files (relative path, blob), $\pi$ |
| `DocIR` $\mathcal{D}$ | $\Phi_1$ | $\Phi_2$ | title, blocks[] (id, type, text, latex, label, level, env, refs, page), macros, bib |
| `KnowledgeGraph` $\mathcal{K}$ | $\Phi_2$ | $\Phi_3$ | nodes (id, kind, name, latex, meaning, key, sources → block ids), edges (src, dst, rel) |
| `Storyboard` $\mathcal{B}$ | $\Phi_3$ | $\Phi_4,\Phi_5,\Phi_6$ | title, scenes[] (id, goal, narration[] (text, bookmark), visuals[] (primitive, args, at), math[], data[], nodes[], duration), symbols |
| `DataSet` | $\Phi_4$ | $\Phi_5$ | request (kind, params), arrays (name → blob), meta |
| `Narration` | $\Phi_6$ | $\Phi_5,\Phi_7$ | scene id, audio blob, duration, words (text, start, end), bookmark times |
| `SceneRender` | $\Phi_5$ | $\Phi_7$ | scene id, clip blob, duration, bookmark times, checks |
| `Manifest` | $\Phi_7$ | user | video, subtitles, artifact digests, versions, timings, usage, metrics |

**Invariants 4.1.**
1. Every artifact carries `schema_version`.
2. A stage computes its input key $k = H(\text{stage}, \text{version}, d_1,\dots,d_m)$ over its input digests and is skipped iff `Store.lookup(kind, k)` succeeds.
3. Validators enforce: unique ids and labels, resolved references, acyclic `depends_on`, visuals cue existing bookmarks, monotone word timings within duration.

## 5 Quality metrics

| Metric | Definition | Target |
|---|---|---|
| $Q_1$ render success | fraction of scenes rendering without manual edit | $\ge 0.95$ |
| $Q_2$ formula fidelity | exact match (normalized LaTeX) on golden set | $1.0$ |
| $Q_3$ sync error | $\max \lvert t_{\text{visual}} - t_{\text{bookmark}}\rvert$ | $\le 150$ ms |
| $Q_4$ layout | overlaps / out-of-frame objects per scene (bounding-box check + VLM) | 0 |
| $Q_5$ coverage | fraction of key nodes of $\mathcal{K}$ addressed in $\mathcal{B}$ | $\ge 0.9$ |
| $Q_6$ duration | $\lvert T_{\text{actual}} - T\rvert / T$ | $\le 0.1$ |
| $Q_7$ pedagogy | rubric (accuracy, logical flow, visual relevance, element layout) by LLM judge + user | $\ge 4/5$ |

## 6 Architecture

### 6.1 Pipeline

| Stage | Map | Module | Deterministic | LLM |
|---|---|---|---|---|
| $\Phi_1$ Ingest | $\mathcal{S}\to\mathcal{D}$ | `ingest` | yes, except PDF transcription (cached) | PDF only |
| $\Phi_2$ Extract | $\mathcal{D}\to\mathcal{K}$ | `extract` | cached | yes |
| $\Phi_3$ Plan | $(\mathcal{K},\pi)\to\mathcal{B}$ | `plan` | cached | yes |
| $\Phi_4$ Compute | data requests $\to$ `DataSet` | `numerics` | yes | no |
| $\Phi_6$ Narrate | $\mathcal{B}\to$ `Narration` | `narrate` | yes | no |
| $\Phi_5$ Animate | $(\mathcal{B},\text{DataSet},\text{Narration})\to$ `SceneRender` | `scene` | cached | codegen fallback, critic |
| $\Phi_7$ Assemble | renders, narration $\to\mathcal{V}$ | `assemble` | yes | no |

$\Phi_4$ and $\Phi_6$ run concurrently after $\Phi_3$; $\Phi_5$ consumes narration timings so animation run times follow speech; scenes in $\Phi_5$ run in parallel.

**Algorithm 6.1 (scene generation, $\Phi_5$).** For each scene $s\in\mathcal{B}$, in parallel:
1. Layout $\mathcal{L}_s$: keyframe bounding boxes on a semantic grid; reject if overlap or off-frame at any keyframe or interpolated frame.
2. Compile $s$ to code from the primitive library; if a visual is not covered, generate code by LLM with retrieval over pinned Manim CE API and vetted snippets.
3. Static gate: AST whitelist of Manim symbols, LaTeX precompile.
4. Draft render (low quality); on error, localized repair (line → block → scene), at most $N_{\text{retry}}$ times.
5. Critic: programmatic mobject-bbox checks, then VLM on sampled keyframes against $s$; record failures in pitfall memory.
6. Final render at target quality.

### 6.2 Package layout

```
animath/
  SPEC.md PROGRESS.md HANDBOOK.md README.md Makefile pyproject.toml requirements.lock
  docker/Dockerfile       TeX Live, dvisvgm, ffmpeg, pandoc, cairo/pango, espeak-ng, node
  src/animath/
    core/                 errors, hashing, schemas, store, config          (WP0)
    llm/                  LLM protocol, Claude adapter, replay cache       (WP0)
    ingest/               md, latex, pdf, macro expansion, equation check  (WP1)
    numerics/             quadrature, Krylov traces, kernels, data cache   (WP2)
    scene/                primitives, layout, render; codegen, repair, critic (WP3, WP8)
    narrate/              verbalization, TTS, alignment, subtitles         (WP4)
    assemble/             concat, loudness, encode, manifest               (WP5)
    extract/              knowledge graph                                  (WP6)
    plan/                 storyboard, symbol ledger, duration budget       (WP7)
    pipeline.py, eval/    orchestration, evaluation                        (WP9)
    cli.py                schema, inspect, config; run, stage              (WP0, WP9)
  tests/                  mirrors src/; golden/ holds reference sources and expected IR
```

**Rule 6.2.** A stage module imports only `core`, `llm`, and its own subpackage; inter-stage coupling is through `core.schemas` only.

### 6.3 Toolchain

| Concern | Primary | Fallback | Reason |
|---|---|---|---|
| Language | Python ≥ 3.12 (3.13 in use) | C++ (nanobind), Fortran (f2py) for profiled kernels | ecosystem; compiled kernels where profiled |
| MD | pandoc JSON AST (subprocess) | markdown-it-py + dollarmath | one AST shared with LaTeX path |
| LaTeX | latexpand → pandoc + Lua filters; pylatexenc for algorithms | LaTeXML (apt) | pandoc fast and typed; LaTeXML full TeX engine |
| PDF | arXiv/source lookup → LaTeX path | pypdfium2 page rasters → Claude vision transcription (MD + LaTeX) | source beats OCR; CPU only |
| PDF references, figures | Claude transcription; pypdfium2 crops | — | no service dependency |
| Equation check | LaTeX compile + SymPy equivalence | — | catches transcription errors |
| LLM | Claude API (`claude-opus-5-5`): structured outputs, cached system prompt, vision, refusal fallback, replay cache | `LLM` protocol | typed contracts, deterministic reruns |
| Animation | Manim CE 0.21 (Cairo) | — | maintained, headless, deterministic |
| 3D fields, meshes | PyVista/VTK offscreen (OSMesa) | — | scientific 3D, headless |
| Typesetting | TeX Live + SVG cache | — | fidelity to source macros |
| Numerics | NumPy/SciPy + Numba | gmsh (subprocess), bempp-cl (optional) | Krylov callbacks expose iterates |
| Data cache | npz blobs keyed by request digest | — | reproducible, decoupled |
| Narration sync | manim-voiceover bookmarks | — | run time bound to speech |
| TTS | Kokoro-82M (local, Apache-2.0) | Azure TTS (SSML, word timings) | free, CPU-viable |
| Math speech | Speech Rule Engine (ClearSpeak, node subprocess) | MathCAT | LaTeX → spoken text |
| Alignment | torchaudio forced alignment | — | known script |
| Encoding | ffmpeg: H.264 High, yuv420p, CRF 18, faststart, AAC 48 kHz, loudnorm −16 LUFS | — | universal playback |
| Quality | ruff, mypy --strict, pytest-cov ($\ge 95\%$), pip-licenses (`make check`) | — | long-term maintainability |

**Trimmed at C1 as infeasible on CPU-only cloud containers or redundant:** MinerU, Marker, Chandra (GPU), GROBID (Java service), Typst, Blender, AV1, WhisperX.

### 6.4 Risks

| Risk | Mitigation |
|---|---|
| Manim API hallucination, CE/GL confusion | primitive library first; symbol whitelist; retrieval over pinned docs |
| Visual defects that render cleanly | deterministic layout check before code; bbox check after render; VLM critic last |
| Wrong mathematics (transcription, derivation) | equation check; provenance to source blocks; approval gate on $\mathcal{K}$ |
| Desync, poor math speech | bookmarks; SRE rules; forced-alignment QA |
| Licence contamination | subprocess boundary; `make licenses` |
| No API key in the container | unit tests use the replay cache; live runs need `ANIMATH_API_KEY` (fallback `ANTHROPIC_API_KEY`) in the environment |
| Heavy image (TeX, VTK, torch) | single pinned image; SVG and model caches |

## 7 Development plan

### 7.1 Work packages

Granular steps live in `PROGRESS.md`. Each work package (WP) is one thread, owns exactly the listed paths (plus `tests/<module>/`), and ends at a checkpoint: `make check` green, review, commit.

| WP | Content | Owns | Depends | Group | Checkpoint |
|---|---|---|---|---|---|
| 0 | Skeleton, tooling, schemas, store, config, LLM adapter, CLI base, Dockerfile | root files, `docker/`, `core/`, `llm/`, `cli.py` | — | A | C1 |
| 1 | Ingestion MD/LaTeX/PDF, equation check, golden set | `ingest/`, `tests/golden/` | 0 | B | C2 |
| 2 | Numerics: quadrature, Krylov traces, MoM/BEM toy kernels, data cache | `numerics/` | 0 | B | C2 |
| 3 | Primitive library, layout checker, renderer wrapper | `scene/primitives/`, `scene/layout.py`, `scene/render.py` | 0 | B | C2 |
| 4 | Narration: verbalization, TTS, alignment, subtitles | `narrate/` | 0 | B | C2 |
| 5 | Assembly and manifest | `assemble/` | 0 | B | C2 |
| 6 | Knowledge-graph extraction | `extract/` | 0, 1 (golden IR) | C | C3 |
| 7 | Storyboard planner, symbol ledger, duration budget | `plan/` | 0, 3 (primitive names) | C | C3 |
| 8 | Codegen, repair loop, critic | `scene/codegen.py`, `scene/repair.py`, `scene/critic.py` | 3, 7 | D | C4 |
| 9 | Orchestrator, CLI `run`/`stage`, evaluation harness, end-to-end on golden set | `pipeline.py`, `eval/`, `cli.py` | all | E | C5 |

Groups run sequentially $A\to B\to C\to D\to E$; WPs within a group run in parallel without shared files. Changes to `core/`, `llm/`, root files (except dependency pins, §7.2), the Dockerfile, or CI after C1 are requested from the integrator, never edited in a WP branch.

### 7.2 Code exchange

1. Code lives in the private GitHub repository `kleasama/animath`; `main` is protected by convention: only the integrator merges.
2. A WP thread branches `wp<N>-<name>` from `main`, keeps `make check` green, and opens a pull request; CI runs `make check`.
3. A WP may add its runtime dependencies to `pyproject.toml` and re-run `make lock`; conflicts in these two files are resolved by the integrator with `make lock`.
4. At each checkpoint the integrator merges the group, records the commit in `PROGRESS.md`, and uploads `SPEC.md`, `PROGRESS.md`, `HANDBOOK.md` to the Drive folder; GitHub is the only code store (the C1 `animath.bundle` in Drive is a one-off snapshot, size-checked only).

## 8 Decisions (C0)

| # | Question | Decision |
|---|---|---|
| Q1 | Code storage | GitHub `kleasama/animath`; Drive holds documents and checkpoint bundles |
| Q2 | Claude API as LLM backend | yes |
| Q3 | Commercial use | no |
| Q4 | GPU available | no |
| Q5 | Default duration 180 s | yes |
| Q6 | Kokoro default TTS | yes |
| Q7 | Golden set chosen by Claude (MoM/EFIE MD, GMRES LaTeX, Gauss quadrature PDF) | yes |
| Q8 | Approval gates on by default | yes |
