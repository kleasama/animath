# Animath

[![check](https://github.com/kleasama/animath/actions/workflows/check.yml/badge.svg)](https://github.com/kleasama/animath/actions/workflows/check.yml)
![python](https://img.shields.io/badge/python-3.12%2B-blue)

Mathematical source (Markdown, LaTeX, PDF) $\to$ short educational MP4, with emphasis on high-performance numerical computing.

| Stage | Map | Module |
|---|---|---|
| $\Phi_1$ Ingest | $\mathcal{S} \to \mathcal{D}$ | `ingest` |
| $\Phi_2$ Extract | $\mathcal{D} \to \mathcal{K}$ | `extract` |
| $\Phi_3$ Plan | $(\mathcal{K}, \pi) \to \mathcal{B}$ | `plan` |
| $\Phi_4$ Compute | data requests $\to$ `DataSet` | `numerics` |
| $\Phi_6$ Narrate | $\mathcal{B} \to$ `Narration` | `narrate` |
| $\Phi_5$ Animate | $(\mathcal{B}, \text{DataSet}, \text{Narration}) \to$ `SceneRender` | `scene` |
| $\Phi_7$ Assemble | renders, narration $\to \mathcal{V}$ | `assemble` |

| Document | Content |
|---|---|
| [`SPEC.md`](SPEC.md) | requirements, contracts, architecture, plan |
| [`PROGRESS.md`](PROGRESS.md) | checklist, notes, open questions |
| [`HANDBOOK.md`](HANDBOOK.md) | developer reference |

```
make setup       # .venv from requirements.lock
make check       # lint, types, tests (coverage ≥ 95%), licence audit
make lock        # re-pin requirements.lock from pyproject.toml
.venv/bin/animath --help
```
