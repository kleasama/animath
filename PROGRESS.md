# Animath — Progress

Legend: ✓ done · ✱ in progress · ○ open · ⏸ checkpoint (review, commit, fresh session).

## Checklist

| Step | Task | Status |
|---|---|---|
| 0.1 | Survey state of the art | ✓ |
| 0.2 | Requirements, architecture, plan (`SPEC.md`) | ✓ |
| 0.3 | Tracker and handbook skeleton | ✓ |
| ⏸ C0 | User approves `SPEC.md`, answers §8 | ✓ |
| 1.1 | `pyproject.toml`, `requirements.lock`, ruff, mypy --strict, pytest-cov gate 95%, `make check` | ✓ |
| 1.2 | `core.errors`: typed exception hierarchy per stage | ✓ |
| 1.3 | `core.schemas`: all contracts of SPEC §4 with validators | ✓ |
| 1.4 | `core.store`: content-addressed, atomic, process-safe artifact store | ✓ |
| 1.5 | `core.config`: settings from defaults, TOML, environment | ✓ |
| 1.6 | `llm`: protocol, Claude adapter, replay cache | ✓ |
| 1.7 | `cli.py` (`schema`, `inspect`, `config`); `docker/Dockerfile` | ✓ |
| 1.8 | Licence audit in `make check`; GitHub Actions CI | ✓ |
| ⏸ C1 | Foundation review (auto-approved); commit `95f0846` | ✓ |
| 2.1 | WP1 ingest: MD → $\mathcal{D}$ | ✓ |
| 2.2 | WP1 ingest: LaTeX flatten, macros, theorems, algorithms → $\mathcal{D}$ | ✓ |
| 2.3 | WP1 ingest: PDF (source lookup, raster + Claude transcription) → $\mathcal{D}$ | ✓ |
| 2.4 | WP1 equation check (compile); golden set and expected IR | ✓ |
| 2.5 | WP2 numerics: quadrature, Krylov with trace capture, MoM/BEM toy kernels, data cache | ✓ |
| 2.6 | WP3 scene: primitive library | ✓ |
| 2.7 | WP3 scene: layout checker, renderer wrapper, PyVista bridge | ✓ |
| 2.8 | WP4 narrate: SRE verbalization, Kokoro and espeak-ng TTS, bookmark timeline, VTT | ✓ |
| 2.9 | WP5 assemble: concat, loudnorm, encode, manifest | ✓ |
| ⏸ C2 | Stage modules review (auto-approved); group B integrated | ✓ |
| 3.1 | WP6 extract: $\mathcal{K}$ with provenance | ✓ |
| 3.2 | WP7 plan: subgraph selection, storyboard, symbol ledger, duration budget | ✓ |
| ⏸ C3 | Semantics review (auto-approved); group C integrated | ✓ |
| 4.1 | WP8 codegen with retrieval, static gate | ✓ |
| 4.2 | WP8 repair loop, critic, pitfall memory | ✓ |
| ⏸ C4 | Scene generation and pipeline review (auto-approved); integrated | ✓ |
| 5.1 | WP9 orchestrator, resume, parallel scenes | ✓ |
| 5.2 | WP9 evaluation harness ($Q_1$–$Q_7$) | ✓ |
| 5.3 | WP9 end-to-end on golden set (session mode) | ✓ |
| ⏸ C5 | Release v0.1 | ✓ |

## Notes

| Step | Note |
|---|---|
| 0.1 | Survey covered ingestion, animation/numerics, generation loop/narration; conclusions in SPEC §6.3–6.4. |
| C1 | Container: 4 cores, 15 GB RAM, no GPU, no TeX preinstalled (apt available), ffmpeg 6.1, pandoc 3.1. GPU parsers, GROBID, Typst, Blender, AV1, WhisperX trimmed (SPEC §6.3). |
| 1.1–1.8 | 41 tests, 100% line+branch coverage, mypy strict clean, licence audit clean. |
| 1.7 | Dockerfile not built: no container runtime in the session. |
| 2.6–2.7 | 8 primitives (`text`, `equation`, `derive`, `matrix`, `plot`, `field`, `surface`, `trace`); grid layout check; frame-exact scheduler; deterministic clips. 100% coverage of `scene/`. Handbook §9. |
| C1 | Code moved to GitHub `kleasama/animath` (user decision). Tag push is refused by the session's git proxy; checkpoints are recorded by commit hash. |
| 2.8 | Kokoro v1.0 weights from the GitHub release (Hugging Face blocked in containers), SHA-256 pinned in the Dockerfile. Model token durations replace forced alignment (HANDBOOK 10.8). |
| 2.4 | SymPy equivalence check deferred to WP9; pandoc 3.9 bundled via `pypandoc-binary` (subprocess). |
| C2 | PRs #1–#5 merged. 220 tests, 100% line+branch coverage, mypy strict, licences clean. For WP7/WP8: complex data refs need `part` ∈ {abs, real, imag}; the planner receives the primitive catalog as an argument (Rule 6.2). |
| C3 | PRs #7, #8 merged. 286 tests, 100% line+branch coverage. For WP9: pass `scene.catalog()` and the numerics kernel schemas into `plan.run`; planner depends on `jsonschema`. |
| 5.3 | Session mode (`llm = session`, PR #12); streamed API calls (PR #11). Golden set at 1080p60, espeak-ng: Q1–Q5 pass on EFIE, Gauss, GMRES; Q6 Gauss 0.153 > 0.1; Q7 4.0–4.5; N1 0.12–0.55. |
| C5 | v0.1 = main after PRs #11–#14. 377 tests, 100% line+branch coverage. |
| v0.2 | PRs #15–#17: Kokoro sentence narration with model word timings, gain and limiter loudness; `h2.rss` RS-S kernel, `hierarchy` primitive, `data.npz` arrays pinned by SHA-256; written-maths captions. 517 tests, 100% line+branch coverage. Pending: #18 pacing, narration of `Line.pause_s` and `Params.wpm`. |
| C4 | PRs #9, #10 merged. `scene.animate` returns `(SceneRender, Usage)` and is the pipeline default; `pipeline.render_only` is the no-LLM path. 362 tests, 100% line+branch coverage. |

## Open questions

| # | Question | Default |
|---|---|---|
| O1 | API key in the environment | `ANIMATH_API_KEY` visible to sessions; API account lacks credit, so live runs use session mode |

## Known bugs

| # | Bug | Owner |
|---|---|---|
| B1 | N1 < 1: planner shows worked values and steps absent from the source | Animation flow and pacing (source values via numerics requests) |
| B2 | Gauss narration 15% over budget (Q6) | Natural narration voice |
| B3 | Repair memo key omits the model tag | integrator |
