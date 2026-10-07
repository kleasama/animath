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
| 2.1 | WP1 ingest: MD → $\mathcal{D}$ | ○ |
| 2.2 | WP1 ingest: LaTeX flatten, macros, theorems, algorithms → $\mathcal{D}$ | ○ |
| 2.3 | WP1 ingest: PDF (source lookup, raster + Claude transcription) → $\mathcal{D}$ | ○ |
| 2.4 | WP1 equation check; golden set and expected IR | ○ |
| 2.5 | WP2 numerics: quadrature, Krylov with trace capture, MoM/BEM toy kernels (Numba), data cache | ○ |
| 2.6 | WP3 scene: primitive library (equation, derivation step, matrix, plot, field, algorithm trace) | ✓ |
| 2.7 | WP3 scene: layout checker, renderer wrapper, PyVista bridge | ✓ |
| 2.8 | WP4 narrate: SRE verbalization, Kokoro service, forced alignment, VTT | ○ |
| 2.9 | WP5 assemble: concat, loudnorm, encode, manifest | ○ |
| ⏸ C2 | Stage modules review; integrate group B | ○ |
| 3.1 | WP6 extract: $\mathcal{K}$ with provenance | ○ |
| 3.2 | WP7 plan: subgraph selection, storyboard, symbol ledger, duration budget | ○ |
| ⏸ C3 | Semantics review; integrate group C | ○ |
| 4.1 | WP8 codegen with retrieval, static gate | ○ |
| 4.2 | WP8 repair loop, critic, pitfall memory | ○ |
| ⏸ C4 | Scene generation review | ○ |
| 5.1 | WP9 orchestrator, resume, parallel scenes | ○ |
| 5.2 | WP9 evaluation harness ($Q_1$–$Q_7$) | ○ |
| 5.3 | WP9 end-to-end on golden set | ○ |
| ⏸ C5 | Release v0.1 | ○ |

## Notes

| Step | Note |
|---|---|
| 0.1 | Survey covered ingestion, animation/numerics, generation loop/narration; conclusions in SPEC §6.3–6.4. |
| C1 | Container: 4 cores, 15 GB RAM, no GPU, no TeX preinstalled (apt available), ffmpeg 6.1, pandoc 3.1. GPU parsers, GROBID, Typst, Blender, AV1, WhisperX trimmed (SPEC §6.3). |
| 1.1–1.8 | 41 tests, 100% line+branch coverage, mypy strict clean, licence audit clean. |
| 1.7 | Dockerfile not built: no container runtime in the session. |
| 2.6–2.7 | 8 primitives (`text`, `equation`, `derive`, `matrix`, `plot`, `field`, `surface`, `trace`); grid layout check; frame-exact scheduler; deterministic clips. 100% coverage of `scene/`. Handbook §9. |
| C1 | Code moved to GitHub `kleasama/animath` (user decision). Tag push is refused by the session's git proxy; checkpoints are recorded by commit hash. |

## Open questions

| # | Question | Default |
|---|---|---|
| O1 | Add `ANTHROPIC_API_KEY` as an environment secret before group C (live extraction and planning)? | yes |

## Known bugs

None.
