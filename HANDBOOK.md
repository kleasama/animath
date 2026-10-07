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

5.1 Interface. `ingest.run(bundle, store, llm, fetch=None, check=None, workers=1) -> (DocIR, Usage)`. Stage key
$$k_{\text{ingest}} = d\big([\text{ingest}, v, d(\text{bundle}), [\text{fetch}\neq\varnothing], [\text{check}\neq\varnothing]]\big); \tag{5.1}$$
a hit returns the stored `DocIR` with zero usage. The orchestrator passes `fetch=ingest.fetch_url`, `check=ingest.compile_errors`.

5.2 Modules.

| Module | Content |
|---|---|
| `blocks` | pandoc (pinned, `pypandoc-binary`) JSON AST $\to$ `Block`s; `document`, `ir` |
| `latex` | flatten, comments, macros, bibliographies, algorithm extraction, `parse` |
| `pdf` | arXiv source lookup, page rasters, transcription, `merge`, `parse` |
| `check` | equation compile check |

5.3 AST map. Display math splits a paragraph; theorem-like, proof, list, figure blocks carry their prose as `text`, display math inline as `$$…$$`, and each display also becomes an `equation` block after the container.

| Pandoc node | Block |
|---|---|
| `Header` | heading, level $\min(\max(\ell,1),6)$, label = explicit id |
| `Para`, `Plain` | paragraph(s) and equation(s) |
| `Math DisplayMath`, raw `equation`/`align`/`gather`/`multline` | equation; `align`$\to$`aligned`, `gather`,`multline`$\to$`gathered` |
| `Div` of a theorem class (§5.4) / `proof` | theorem (`env` = class) / proof |
| `BulletList`, `OrderedList` | list, one line per item |
| `Figure` | figure, `text` = caption |
| `CodeBlock` | code |
| token `ANIMATHALG<i>` | algorithm $i$ (Algorithm 5.1) |
| other | paragraph of all inline text; `HorizontalRule`, non-math raw blocks dropped |

5.4 Theorem classes: fixed set (`blocks.THEOREMS`) $\cup$ `\newtheorem` names. LaTeX heads (`Theorem 1`, `Proof.`) are stripped; an optional name stays as `(Name).`.

5.5 Labels and references. An equation takes its first `\label`; later labels of the same display are aliases rewritten in `refs`. `\label`, `\nonumber`, `\notag` are removed from `latex`. Inline forms: `\eqref{l}` $\to$ `(l)`, `\ref{l}` $\to$ `l`, citations $\to$ `[k₁; k₂]`. Unresolved refs raise `IngestError` (MD, LaTeX).

**Algorithm 5.1 (LaTeX).**
1. Decode UTF-8, else Latin-1; strip comments (`%` not preceded by an odd run of `\`).
2. Resolve `\input`/`\include` recursively relative to the entry directory; cycles and missing files raise.
3. Macros: `\(re|provide|new)command`, `\DeclareMathOperator`, `\def` $\mapsto$ full declaration (`DocIR.macros`).
4. Bibliography: `thebibliography` items; then `<entry>.bbl` if present, else `\bibliography`/`\addbibresource` `.bib` files (author, title, journal | booktitle, publisher, year).
5. Replace `algorithm`/`algorithmic` environments by tokens; text = caption, then algorithmic(x) steps, one per line, indented by nesting.
6. Pandoc `latex-auto_identifiers` (macros expanded in math); map by §5.3.

**Algorithm 5.2 (PDF).**
1. If `fetch` is given and page 1 carries an arXiv identifier, fetch `arxiv.org/e-print/<id>`; a TeX source (tar or single file; main = `\documentclass` and `\begin{document}`, shallowest path) goes to Algorithm 5.1. Fetch or unpack failure is logged, then step 2.
2. Render pages at scale 2 (144 dpi) to PNG.
3. Chunks of 4 pages, transcribed in parallel (`workers`) into `pdf.Transcript` by `llm.parse` (structured output, system prompt `pdf.SYSTEM`).
4. If `check` is given, equations failing Algorithm 5.3 are returned to the model with their errors; at most $N_{\text{retry}}$ repairs, then `IngestError`.
5. Merge: title = first non-null; duplicate labels dropped after the first; equations without LaTeX become paragraphs; levels kept for headings only; refs filtered to known labels and bib keys.

**Algorithm 5.3 (equation check).** Equations with unbalanced braces fail without TeX. The rest are typeset in one `pdflatex -draftmode` run (amsmath, amssymb, bm, document macros), each preceded by `\typeout{@@animath-eq-i}`; the first `! ` line after marker $i$ is the error of equation $i$; an error before any marker is a preamble error and raises.

5.6 Golden set (`tests/golden/`): sources, PDF transcription fixture, expected IR (`expected.json`). Regenerate with `ANIMATH_UPDATE_GOLDEN=1 .venv/bin/pytest tests/ingest/test_golden.py`, then review the diff.

| Case | Format | Exercises |
|---|---|---|
| `efie` | MD + `.bib` | YAML title, labelled `$$`, raw `\eqref`, citations, theorem div, list |
| `gmres` | LaTeX, `\input`, `.bib` | macros, `align` aliases, algorithm, named theorem, proof, lemma |
| `gauss` | PDF + transcript | raster, replay, merge, theorem with display |

5.7 Decisions.

| # | Decision | Reason |
|---|---|---|
| I1 | pandoc pinned through `pypandoc-binary` (pandoc 3.9) rather than the system binary | identical AST across image, CI, laptops (N2) |
| I2 | Equation check by TeX compilation only; SymPy equivalence deferred to evaluation (WP9) | catches transcription syntax errors at ingest cost $O(1)$ TeX runs per chunk |
| I3 | PDF output normalized (Algorithm 5.2, step 5), not rejected | model output is a hint; LaTeX/MD inputs stay strict |
| I4 | Figure image paths not kept | `Block` has no field; captions suffice for $\Phi_2$ |

5.8 Performance: pandoc call ≈ 10 ms; `tests/ingest` ≈ 4 s on 4 cores.

## 6 Knowledge extraction
## 7 Storyboard
## 8 Numerics
## 9 Scenes and rendering
Algorithm 9.1 Scene generation: SPEC Algorithm 6.1.
## 10 Narration
## 11 Assembly
## 12 Evaluation
## 13 Performance metrics

| Item | Value |
|---|---|
| `make check` wall time (WP0) | ≈ 5 s on 4 cores |

## 14 Decisions log

| # | Date | Decision | Reason |
|---|---|---|---|
| D1 | 2026-10-07 | Code in GitHub `kleasama/animath`; Drive holds documents only | parallel WPs need a git remote |
| D2 | 2026-10-07 | C0 defaults accepted (SPEC §8) | user approval |
| D3 | 2026-10-07 | CPU-only toolchain; GPU parsers replaced by Claude vision transcription | no GPU in containers |
| D4 | 2026-10-07 | Schemas frozen at C1; changes only through integrator | parallel WPs without conflicts |
| D5 | 2026-10-07 | Commits authored by the user, no co-author trailers | user preference |
| D6 | 2026-10-07 | `requirements.lock` instead of `uv.lock` (177 kB) | Drive transfer size |
