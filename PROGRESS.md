# Animath — Progress

Legend: ✓ done · ✱ in progress · ○ open.

## Checklist

| # | Item | HANDBOOK | Status |
|---|---|---|---|
| 1 | Tooling: lock file, ruff, mypy `--strict`, coverage gate, licence audit, CI | §2 | ✓ |
| 2 | `core`: errors, schemas, content-addressed store, config, formula matching | §3 | ✓ |
| 3 | `llm`: protocol, Claude adapter, replay cache, session mode | §4 | ✓ |
| 4 | Ingest MD, LaTeX, PDF; equation check; golden set | §5 | ✓ |
| 5 | Extract $\mathcal{K}$ with provenance | §6 | ✓ |
| 6 | Plan: selection, storyboard, pacing, loops, views, formula tracing | §7 | ✓ |
| 7 | Numerics: quadrature, Krylov traces, MoM, BEM, `h2.rss`, `data.npz` | §8 | ✓ |
| 8 | Scene: primitives, layout, renderer, codegen, repair, critic | §9 | ✓ |
| 9 | Narrate: math speech, Kokoro and espeak-ng, word timeline, captions | §10 | ✓ |
| 10 | Assemble: concatenation, loudness, encoding, subtitles, manifest | §11 | ✓ |
| 11 | Pipeline: resume, gates, parallel scenes, budget; evaluation | §12 | ✓ |
| 12 | Docker image built and run in CI | §1.6 | ○ |
| 13 | Golden set re-run and evaluated with the current pacing model | §12.6 | ○ |

## Status

| Item | Value |
|---|---|
| Tests | 623 passed, 1 skipped; 100 % line and branch coverage |
| Last golden evaluation (EFIE, Gauss, GMRES; 1080p60, espeak-ng) | $Q_1$–$Q_5$ pass; $Q_6$ Gauss 0.153 > 0.1; $Q_7$ 4.0–4.5; $N_1$ 0.12–0.55; predates the spoken-word pacing and planner formula tracing |

## Milestones

| Milestone | Content |
|---|---|
| 0.1 | Full pipeline, session mode, evaluation harness |
| 0.2 | Kokoro sentence narration with model word times; gain and limiter loudness; `h2.rss`, `hierarchy`, `data.npz`; written-maths captions |
| 0.3 | `wpm` pacing and pauses; word-timed actions; loops; persistent views; `code` primitive in the planner; byte-identical clips |
| 0.4 | Word-timed `hierarchy` verbs; one voice speed per video; planner length from spoken words |
| 0.5 | Planner traces on-screen formulas (Algorithm 12.3) |

## Open questions

| # | Question | Default |
|---|---|---|
| O1 | Live API runs | need a funded `ANIMATH_API_KEY`; session mode runs without one |

## Known bugs

None.
