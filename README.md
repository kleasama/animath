# Animath

Mathematical source (Markdown, LaTeX, PDF) $\to$ short educational MP4.

| Document | Content |
|---|---|
| `SPEC.md` | requirements, contracts, architecture, plan |
| `PROGRESS.md` | checklist, notes, open questions |
| `HANDBOOK.md` | developer reference |

```
make setup       # .venv from requirements.lock
make check       # lint, types, tests (coverage ≥ 95%), licence audit
make lock        # re-pin requirements.lock from pyproject.toml
.venv/bin/animath --help
```
