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
| `.venv/bin/animath run <src> [-p k=v] [--pages 3-7] [--section 2.1] [--approve \| --edit f]` | $\Phi$; pauses at gates (§12.3) |
| `.venv/bin/animath stage <name> <digest> [-p k=v]` | one stage on a stored input (F11) |
| `.venv/bin/animath eval <manifest> [--expected doc.json] [--judge]` | $Q_1$–$Q_7$, $N_1$ (§12.5) |

2.3 Settings (`core.config.Settings`): defaults, then TOML file (`--config`), then `ANIMATH_<FIELD>` variables. Fields: `store`, `model`, `effort`, `max_tokens`, `workers`, `offline`. Online, the API key is `ANIMATH_API_KEY`, else `ANTHROPIC_API_KEY` (reserved in cloud environments); none raises `LLMError`.
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

6.1 Interface. `extract.run(doc, store, llm, retries=3) -> (KnowledgeGraph, Usage)` realizes $\Phi_2$. Stage key
$$k_{\text{extract}} = d\big([\text{extract}, v, d(\mathcal{D})]\big); \tag{6.1}$$
a hit returns the stored graph with zero usage. The orchestrator passes `retries` $= N_{\text{retry}}$.

6.2 Modules.

| Module | Content |
|---|---|
| `draft` | LLM output schema `Draft` (`DNode`, `DEdge`), system prompt `SYSTEM`, block lines, `chunks`, `prompt` |
| `graph` | node validation (`node`), fold of a draft into the graph (`merge`) |

6.3 Semantics. Node kinds: concept, symbol (with `latex`, `meaning`), equation (one display), result, algorithm. Edges: $a \xrightarrow{\text{depends\_on}} b$ iff $a$ cannot be understood before $b$; $a \xrightarrow{\text{defines}} b$ iff $a$ introduces $b$; $a \xrightarrow{\text{uses}} b$ otherwise. `Node.sources` are `DocIR` block ids; `key` marks the nodes $\mathcal{K}^\ast$ a video must cover, so $Q_5 = |\{n\in\mathcal{K}^\ast : n \in \bigcup_s \text{nodes}(s)\}| / |\mathcal{K}^\ast|$.

**Algorithm 6.1 (extraction).**
1. Split $\mathcal{D}$ into sections (heading to heading); pack sections greedily into chunks of at most $C = 4\cdot 10^4$ characters of block lines `[id type env label] latex|text`; a longer section is packed block by block.
2. For each chunk, in order: prompt = title, macros, known nodes (`id (kind): name`), block lines; `llm.parse(Draft, SYSTEM, prompt)`.
3. Merge (Algorithm 6.2). On problems, re-prompt with the previous draft and the problem list; at most $N_{\text{retry}}$ repairs, then `ExtractError`.
4. Store the graph under (6.1).

**Algorithm 6.2 (merge).** For each draft node: reject unless the id matches `[a-z0-9][a-z0-9_-]*`, all sources are block ids, an equation has an equation block among its sources, a symbol has `latex` and `meaning`; an equation's `latex` is replaced by that of its first equation source. A known id with the same kind unites sources and `key`; a different kind is a problem. Edges must join known nodes without self-loops; duplicates are dropped. After the last chunk at least one node is key. The candidate is validated by `KnowledgeGraph` (unique ids, resolved edges, acyclic `depends_on`, Kahn); its errors are problems.

6.4 Golden drafts (`tests/extract/golden/<case>.json`) are hand-written `Draft`s for the IR of §5.6; the test replays each through `Replay` and checks key nodes, sources, equation fidelity and offline reruns.

6.5 Decisions.

| # | Decision | Reason |
|---|---|---|
| X1 | Equation node `latex` copied from $\mathcal{D}$, never from the model | $Q_2$ and N1 by construction |
| X2 | Invalid drafts repaired by the model, not normalized | the graph gates planning (F12); silent drops would hide errors (N4) |
| X3 | Chunks processed sequentially with a ledger of known nodes | cross-chunk ids and edges; golden documents fit one chunk |
| X4 | Stage key excludes $\pi$ | audience and focus act in $\Phi_3$ (F4) |

## 7 Storyboard

7.1 Interface. `plan.run(graph, params, catalog, store, llm, kernels=None) -> (Storyboard, Usage)` realizes $\Phi_3$. `catalog` maps primitive names to argument JSON schemas (`scene.catalog()`), `kernels` maps data kinds to parameter JSON schemas (`{k: K.model_json_schema() for k, K in numerics.KINDS.items()}`); both are passed by the orchestrator (Rule 6.2). With $\pi_3$ = (`duration_s`, `audience`, `focus`, `language`, `max_retries`),
$$k_{\text{plan}} = d\big([\texttt{plan}, v, d(\mathcal{K}), d([\pi_3, \text{catalog}, \text{kernels}])]\big). \tag{7.1}$$

| Module | Content |
|---|---|
| `select` | seeds, prerequisite closure, budget, topological order (Algorithm 7.1) |
| `draft` | LLM output schema `Draft`, system prompt, task prompt |
| `check` | validation and conversion to `Storyboard` (Algorithm 7.2) |

**Algorithm 7.1 (selection, F4).**
1. Seeds $S$: nodes whose id or a source block equals `focus`, or whose name contains it (case-folded); no match raises `PlanError`. Without focus: key nodes, else the nodes no `depends_on` edge points to.
2. Breadth-first closure from $S$ along all out-edges; hop $h(v)$; expansion stops at depth $\delta$ = ∞, 2, 1 for undergraduate, graduate, expert.
3. Budget $N = \max(|S|, \lceil T/15 \rceil)$: keep the $N$ nodes least in $(h, \text{graph order})$; seeds and every kept node's parent survive.
4. Order by Kahn's algorithm on `depends_on` (prerequisite first), ties by graph order.

7.2 Draft. The model returns `Draft`: scenes with lines, visuals (`args` a JSON string), data requests (`params` a JSON string), node ids, symbols. JSON strings keep the output schema closed for structured outputs. The prompt carries audience, $T$, scene target $\max(1, \operatorname{round}(T/30))$, word target $\operatorname{round}(rT)$, seeds, selected nodes and edges, catalog, kernels.

7.3 Spoken length. With $r = 2.5$ words/s and $w(\ell)$ the number of TeX control words and alphanumeric runs of line $\ell$, scene $i$ has $w_i = \max(1, \sum_{\ell} w(\ell))$, $W = \sum_i w_i$. The draft is admissible only if
$$\lvert W/r - T \rvert \le 0.1\,T, \tag{7.2}$$
and scene durations are word-proportional,
$$d_i = T\,w_i / W, \qquad \textstyle\sum_i d_i = T, \tag{7.3}$$
rounded to 1 ms. Since run time follows speech (§9.6, §11.2), (7.2) bounds $Q_6$ up to the speech-rate estimate.

**Algorithm 7.2 (validation).** Errors are collected, not raised:

| Check | Rule |
|---|---|
| primitive | name in catalog; `args` a JSON object valid against its schema (JSON Schema 2020-12) |
| arrays | every `{"data", "array"}` object names an existing data request; `part` set outside `matrix` |
| data | `params` a JSON object; if kernels given, kind known and params valid |
| cues | `at` names a bookmark (`Scene` validator); `until` names a later bookmark |
| regions | lifetimes $[\iota(\texttt{at}), \iota(\texttt{until}))$ in line indices, defaults $0$ and $m$; overlapping lifetimes need disjoint regions (`main` meets `left`, `right`) |
| scene | at least one visual; nodes within the selection; `Scene` validators |
| board | (7.2); seed coverage $\ge 0.9$ ($Q_5$); unique scene ids |

7.4 Symbol ledger. `Storyboard.symbols` = draft symbols, overridden by selected symbol nodes (`latex` $\mapsto$ `meaning`, else `name`).

**Algorithm 7.3 (plan).** Key hit $\Rightarrow$ return. Else select; for at most $N_{\text{retry}}+1$ attempts: parse `Draft`, validate; on success store and return; else append the previous draft and its errors to the base prompt. Exhaustion raises `PlanError` with the last errors. Usage is summed over attempts.

7.5 Decisions.

| # | Decision | Reason |
|---|---|---|
| P1 | Selection deterministic, LLM only for scenes and prose | reproducible F4, smaller prompt |
| P2 | Durations from words (7.3), not from the model | $\sum d_i = T$ exactly; consistent with narration-driven timing |
| P3 | `part` required on every non-matrix array ref | real/complex is unknown before $\Phi_4$; `real` on real data is the identity |
| P4 | Region conflicts checked at plan time | cheap pre-check of §9.5, saves renders and repairs |
| P5 | `jsonschema` validates against the catalog | catalog is JSON Schema; no import of `scene` |

7.6 Performance: `tests/plan` ≈ 5 s on 4 cores (dominated by importing `scene` for the real catalog).
## 8 Numerics

8.1 Interface. `numerics.compute(request, store) -> DataSet` realizes $\Phi_4$. `request.kind` selects a `Kernel` (frozen Pydantic parameters with bounds, `run() -> (arrays, meta)`, pure); invalid kinds or parameters, `LinAlgError`, and non-finite arrays raise `ComputeError`. `numerics.load(ds, store)` returns the arrays.

8.2 Cache. With $p$ the validated parameters (defaults filled),
$$k = d\big([\texttt{numerics}, v, \text{kind}, d(p)]\big). \tag{8.1}$$
Each array is one blob in `.npy` format (`allow_pickle=False`); `meta.version` $= v$.

8.3 Kinds:

| Kind | Parameters | Arrays | Meta |
|---|---|---|---|
| `quadrature.rule` | `n`, `a`, `b` | `nodes`, `weights` | `degree` |
| `quadrature.convergence` | `integrand` ∈ {exp, runge, osc, abs}, `a`, `b`, `n_max` | `n`, `gauss`, `trapezoid`, `simpson` | `exact` |
| `mom.efie_cylinder` | `ka`, `n` ($n \ge 10\,ka$) | `phi`, `current`, `exact` | `rel_error` |
| `bem.dlp_ellipse` | `a`, `b`, `n_max` | `n`, `error`, `t`, `density` | `target` |
| `krylov.gmres` | `operator`, `tol`, `maxiter` $\le 256$, `ritz` | `x`, `residual`, `eigs`, `ritz`, `ritz_k` | `iterations`, `converged`, `true_residual` |
| `krylov.cg` | `operator`, `tol`, `maxiter` | `x`, `residual`, `error_a`, `bound` | `kappa`, `iterations`, `converged` |

Operators (discriminator `name`): `poisson1d` $\operatorname{tridiag}(-1,2,-1)$; `convdiff` $\operatorname{tridiag}(-1-P,2,-1+P)$, $P$ the cell Péclet number; `efie` (§8.5); `dlp` (§8.6). Right-hand sides: $\mathbf{1}$, $\mathbf{1}$, $\mathbf{V}$, $g$.

8.4 Quadrature. Gauss–Legendre nodes $x_i$ are the eigenvalues of the Jacobi matrix $J_n$ with $J_{k,k+1} = k/\sqrt{4k^2-1}$; weights $w_i = 2 v_{i,1}^2$ (Golub–Welsch). The rule is exact on $\mathbb{P}_{2n-1}$ with remainder
$$\int_a^b f - Q_n f = \frac{(b-a)^{2n+1}(n!)^4}{(2n+1)\,((2n)!)^3}\, f^{(2n)}(\xi). \tag{8.2}$$
Convergence data use $n = 3,5,\dots$ points for all rules, so composite Simpson is defined.

8.5 MoM, TM EFIE on a PEC cylinder of radius $a$, $\lambda = 1$, $E^i_z = e^{-jkx}$, time convention $e^{j\omega t}$:
$$E^i_z(\boldsymbol\rho) = \frac{k\eta}{4}\int_C J_z(\boldsymbol\rho')\,H_0^{(2)}(k|\boldsymbol\rho-\boldsymbol\rho'|)\,dl'. \tag{8.3}$$
Pulse basis, point matching at $n$ equispaced points, $w = 2\pi a/n$:
$$Z_{mn} = \frac{k\eta w}{4}H_0^{(2)}(kR_{mn}),\quad Z_{mm} = \frac{k\eta w}{4}\Big[1 - \frac{2j}{\pi}\ln\frac{\gamma k w}{4e}\Big],\ \gamma = e^{\gamma_E}. \tag{8.4}$$
Reference: $J_z(\phi) = \frac{2}{\pi\eta\, ka}\sum_{m} j^{-m} e^{jm\phi}/H_m^{(2)}(ka)$, truncated at $|m| \le ka + 4(ka)^{1/3} + 10$. Error is $O(1/n)$.

8.6 BEM, interior Dirichlet problem by the double-layer potential with $\Phi(x,y) = -\frac{1}{2\pi}\ln|x-y|$:
$$-\tfrac12\mu(x) + \int_\Gamma \frac{\partial \Phi(x,y)}{\partial\nu_y}\mu(y)\,ds_y = g(x),\qquad \lim_{y\to x}\frac{\partial\Phi}{\partial\nu_y} = -\frac{\kappa(x)}{4\pi}. \tag{8.5}$$
Nyström discretization with the trapezoid rule on $y(t) = (a\cos t, b\sin t)$; test data $u = e^{x_1}\cos x_2$ evaluated at $(a/4, b/4)$. Error decays exponentially in $n$. Check: $A\mathbf 1 = -\mathbf 1$ (Gauss lemma).

**Algorithm 8.1 (GMRES with trace).** $x_0 = 0$, $\beta = \|b\|$, $v_1 = b/\beta$. For $k = 1,\dots,m$: Arnoldi step by modified Gram–Schmidt giving column $k$ of $\bar H_k$; record Ritz values $\sigma(H_k)$; apply previous Givens rotations to the column, form $G_k$ annihilating $h_{k+1,k}$, update $g$; $\|r_k\|/\beta = |g_{k+1}|/\beta$. Stop when $\le$ `tol` or $h_{k+1,k} \le 10^{-14}\|Av_k\|$ (happy breakdown). Then $x_k = V_k R_k^{-1} g_{1:k}$. Ritz values: cost $O(m^4)$, hence `maxiter` $\le 256$.

**Algorithm 8.2 (CG with trace).** Requires $A = A^H \succ 0$ (symmetry test, Cholesky). Records $\|r_k\|/\|b\|$ and $\|e_k\|_A/\|e_0\|_A$ with $e_k = x_k - A^{-1}b$, bounded by
$$\frac{\|e_k\|_A}{\|e_0\|_A} \le 2\Big(\frac{\sqrt\kappa-1}{\sqrt\kappa+1}\Big)^k. \tag{8.6}$$

8.7 Implementation notes. Dense NumPy/SciPy, vectorized assembly; all kernels are deterministic and side-effect free, so concurrent `compute` calls are safe (store writes are atomic, §3.4). Numba is deferred until a profile demands it (D7). Matrix symbols ($A$, $H$, $R$, $V$) keep textbook case; `N803`/`N806` are silenced per file.
## 9 Scenes and rendering

Algorithm 9.1 Scene generation: SPEC Algorithm 6.1.

9.1 Modules. `scene.layout` (geometry, no Manim), `scene.primitives` (registry `PRIMITIVES`, `catalog()` of argument JSON schemas), `scene.render` (`timeline`, `compose`, `schedule`, `render`).

9.2 Primitives. A `Visual` names a primitive and carries its arguments; every argument model extends `Args` with `region` (default `main`) and `until` (bookmark that removes the visual). Numerical arguments are literals or `ArrayRef` $(i, a)$: array $a$ of the `DataSet` answering `scene.data[i]`, stored as one `.npy` blob and loaded with `allow_pickle=False`. Complex arrays must select `part` $\in$ {`abs`, `real`, `imag`} wherever a real array is drawn (`plot`, `field`, `surface`); `matrix` takes complex input directly.

| Primitive | Arguments | Visual | Cues |
|---|---|---|---|
| `text` | `text` (LaTeX text mode) | `Tex` | write |
| `equation` | `latex` | `MathTex` | write |
| `derive` | `steps` ($\ge 2$; `{{...}}` marks matched parts) | `MathTex` chain | write, then `TransformMatchingTex` at $t_0 + k(t_1-t_0)/n$ |
| `matrix` | `entries` (strings or `ArrayRef`) | entries if $\max(m,n) \le 8$, else heatmap of $\log_{10}\lvert a_{ij}\rvert$ | write or fade in |
| `plot` | `series` ($\le 5$; `x`, `y`, `label`), `xlabel`, `ylabel`, `logy` | `Axes`, line graphs, legend | write |
| `field` | `values` $u_{ij}$ at $(x_j, y_i)$, $y$ upward | viridis heatmap | fade in |
| `surface` | `points` $(n,3)$, `faces` $(m,3)$, `scalars` $(n)$ or $(m)$, `azimuth`, `elevation` | PyVista offscreen image | fade in |
| `trace` | `lines`, `steps` (line indices) | monospace listing, cursor | write, then cursor to line `steps[i]` at $t_0 + i(t_1-t_0)/n$ |

9.3 Semantic grid. For frame $F = [-W/2, W/2] \times [-H/2, H/2]$, $H = 8$, $W = 8w/h$, a region with normalized box $(u_0, v_0, u_1, v_1)$ occupies
$$C = [-W/2 + u_0 W,\; -W/2 + u_1 W] \times [-H/2 + v_0 H,\; -H/2 + v_1 H]. \tag{9.1}$$

| Region | $(u_0, v_0, u_1, v_1)$ |
|---|---|
| `title` | (0.04, 0.86, 0.96, 0.97) |
| `main` | (0.04, 0.14, 0.96, 0.84) |
| `left` | (0.04, 0.14, 0.49, 0.84) |
| `right` | (0.51, 0.14, 0.96, 0.84) |
| `footer` | (0.04, 0.03, 0.96, 0.12) |

`left` and `right` partition `main`; using either with `main` at the same time is a conflict.

9.4 Fit. A mobject of size $w \times h$ in cell $C$ is scaled by
$$s = \min\big(1,\; w_C / w,\; h_C / h\big) \tag{9.2}$$
and centred in $C$. Raster primitives are built at cell height.

9.5 Layout check. A placement is $p = (B_p, [t_0, t_1), s_p)$ with $B_p$ the measured bounding box. The layout is rejected (`AnimateError`) iff for some $p$: $B_p \not\subseteq F$, or $s_p < s_{\min} = 0.4$; or for some $p \ne q$:
$$[t_0^p, t_1^p) \cap [t_0^q, t_1^q) \ne \emptyset \;\wedge\; \lvert B_p \cap B_q \rvert > 0. \tag{9.3}$$
Placements are static between cues and exits end at $t_1$, so (9.3) at keyframes covers every interpolated frame.

9.6 Timeline. With narration, bookmark times $\tau_b$ and duration $T$ are taken from `Narration` (every scene bookmark must be present). Without, line $i$ of $n$ starts at
$$\tau_i = iT/n, \quad T = \texttt{duration\_s}. \tag{9.4}$$
A visual lives on $[t_0, t_1)$ with $t_0 = \tau_{\texttt{at}}$ (else 0) and $t_1 = \tau_{\texttt{until}}$ (else $T$); its exit fades over $[\max(t_0, t_1 - 0.5), t_1)$.

**Algorithm 9.2 (schedule).** Input cues $(t_k, r_k)$, frame rate $f$.
1. $n_k = \operatorname{round}(t_k f)$; drop cues with $n_k \ge \operatorname{round}(Tf)$.
2. Group cues by $n_k$; let $n^{(1)} < \dots < n^{(g)}$, $n^{(g+1)} = \operatorname{round}(Tf)$.
3. Group $j$ plays from $n^{(j)}/f$ for $\max\big(1, \min(\operatorname{round}(f \max_k r_k),\, n^{(j+1)} - n^{(j)})\big)/f$.
4. Waits fill gaps to the next absolute frame.

Every cue starts on its own frame, so $Q_3 \le 1/(2f)$, and the clip has exactly $\operatorname{round}(Tf)$ frames.

9.7 Rendering. `render(scene, params, store, narration, datasets, draft)` sets Manim's configuration inside `tempconfig`, renders into a temporary directory removed on exit, stores the silent H.264 clip as a blob, and returns `SceneRender` with `checks = {layout, render}`. Draft: 240 px height, 15 fps. Output is byte-identical across runs. Manim's global configuration and VTK make `render` thread-unsafe; parallelize over processes.

9.8 Implementation notes.
1. `manim.Scene.play` overwrites `self.duration`; the clip end time is kept in `Clip.t_end`.
2. PyVista renders through OSMesa (`VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow`, set if absent); requires `libosmesa6`.
3. Build failures (e.g. LaTeX errors) are re-raised as `AnimateError` naming `scene.visual:primitive`, for the WP8 repair loop.
4. Tests run Manim under `tempconfig` with a temporary `media_dir`; nothing is written to the working tree.

9.9 Scene generation (WP8). `scene.animate(scene, data, narration, store, llm, params) -> (SceneRender, Usage)` realizes $\Phi_5$; `data` maps request digests to `DataSet`; `Usage` sums every LLM call of the invocation (codegen, repair, critic) and is zero on a key hit. With $\pi_5$ = (`width`, `height`, `fps`, `max_retries`) and $D_s = [d(\text{DataSet of } r) \text{ or null} : r \in \texttt{scene.data}]$,
$$k_{\text{animate}} = d\big([\texttt{animate}, v, d(s), d([D_s, d(\text{Narration}) \text{ or null}, \pi_5])]\big). \tag{9.5}$$

| Module | Content |
|---|---|
| `codegen` | static gate, `code` primitive, pinned API |
| `repair` | localized LLM patch, pitfall memory |
| `critic` | keyframes, cell content check, VLM verdict |
| `animate` | Algorithm 9.3, stage key |

**Algorithm 9.3 (animate).** Key hit $\Rightarrow$ return. Else, with `code` registered:
1. $E$ ← visuals whose primitive is not in `PRIMITIVES` (codegen requests).
2. For at most $N_{\text{retry}}+1$ rounds: if $E \ne \emptyset$, patch $s$ by `repair` (a rejected patch leaves $s$ unchanged, appends its error to $E$ and ends the round); $E$ ← first non-empty of: static gate of every `code` visual; draft render (`AnimateError`); critic. If $E = \emptyset$: final render, store under (9.5), return. Else record $E$ in pitfall memory.
3. Exhaustion raises `AnimateError` with the last $E$.

Hence at most $N_{\text{retry}}$ repairs follow the first check; codegen is the repair of round 1.

9.10 `code` primitive. Arguments `code`, `region`, `until`. The snippet is exactly `def build(array)` returning one `Mobject`; `array(i, name, part=None)` is `Context.real` on `ArrayRef(i, name, part)`. It enters by `Write`/`FadeIn` and is fitted by (9.2) like any primitive. The gate admits names from a whitelist (32 mobject classes, direction and colour constants, 14 builtins), `np.f` for 29 NumPy functions only, and rejects imports, `while`, `try`, `with`, `raise`, `global`, class definitions, and attributes with prefixes `_`, `f_`, `gi_`, `co_`, `cr_`, `ag_`, `tb_` or names `format`, `save`, `tofile`, `dump`. Execution uses a namespace of exactly these symbols. Runtime errors report the snippet line. The gate filters model errors; it is not a security boundary.

9.11 Localization. Every error names visual $i$ of scene $s$ as `s.i:primitive` (render, gate and critic alike). `repair` may replace only the visuals named in $E$ (block level; snippet line numbers give line level), else all visuals (scene level). The model returns `Patch` = [(index, primitive, args as JSON string, at)]; a patch outside the allowed indices, with non-object `args`, or yielding an invalid `Scene` is rejected. The prompt carries goal, narration, math, data requests, indexed visuals, $E$, allowed indices and pitfalls; the system prompt carries the catalog (with `code`), region sizes and the pinned API (constructor parameters, at most 8 per class), so it is cached.

9.12 Critic. Keyframes: for consecutive change frames $a < b$ of the visual set, frame
$$n = \max\big(a,\; b - 1 - \operatorname{round}(0.5 f)\big), \tag{9.6}$$
i.e. after entries and before exits, kept if a visual is alive; at most 6, evenly subsampled. A visual alive at $n$ with $n \ge \operatorname{round}((t_0 + 1)f)$ fails if its grid cell has no pixel above 16 (of 255). Only if no visual fails, the model receives the keyframes as PNG with the plan and returns `Verdict` (issues with optional visual index).

9.13 Pitfall memory. Index namespace `pitfall`, key $H(\text{primitive})$ (`scene` for unlocalized errors), value a blob with the last 8 distinct messages (300 characters each). Read-modify-write is last-writer-wins across processes; a lost entry only weakens a hint.

9.14 Notes.
1. `animate` registers `code` in `PRIMITIVES` for its duration; with the renderer this makes it thread-unsafe: parallelize scenes over processes (WP9). `scene.catalog()` stays free of `code`, so the planner never emits it.
2. LaTeX precompile is the build phase of the draft render: `compose` builds every mobject before any frame, and build errors are localized.
3. Unit tests use a queued fake LLM (`tests/scene/fake.py`); no network.
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

11.1 Interface. `assemble.assemble(store, board, renders, narrations, threads=1) -> str` maps the digests of a `Storyboard`, its `SceneRender`s and `Narration`s (any order, matched by `scene_id`) to the digest of a `Manifest`. Key $k = d([\texttt{assemble}, v, p, d_{\mathcal{B}}, d^R_1,\dots,d^R_N, d^N_1,\dots,d^N_N])$ in scene order, $p$ = threads; hit $\Rightarrow$ no work.

11.2 Timeline. Scene $i$ has render duration $d^R_i$, narration duration $d^N_i$, frame rate $f$ (common to all clips), audio rate $R = 48$ kHz. With $d_i = \max(d^R_i, d^N_i)$,
$$n_i = \lceil f d_i - 10^{-6} \rceil,\qquad T_i = \frac{1}{f}\sum_{j<i} n_j,\qquad S_i = \operatorname{round}(R\,T_{i+1}) - \operatorname{round}(R\,T_i). \tag{11.1}$$
Segment $i$ is exactly $n_i$ frames and $S_i$ samples; $\sum_i S_i = \operatorname{round}(R\,T_{N})$, so audio–video drift is below one sample for any $N$. Subtitle cue times are word times plus $T_i$.

**Algorithm 11.1 (assemble).**
1. Load artifacts; require renders and narrations to cover the storyboard scenes bijectively.
2. Probe clips: equal width, height, $f$; $\lvert \text{probe} - \text{claimed}\rvert \le 0.1$ s for every clip and audio.
3. Compute (11.1); build WebVTT (§11.3).
4. Loudness pass 1: concatenate trimmed narration, `loudnorm` (EBU R128, $I=-16$ LUFS, $TP=-1.5$ dBTP, $LRA=11$) measurement; silent narration is an error.
5. Pass 2, one `ffmpeg` call: per clip `fps`, `tpad` (clone last frame), `trim` to $n_i$; per narration resample to $R$ mono, `apad`, `atrim` to $S_i$; `concat`; linear `loudnorm` with measured values; H.264 High, yuv420p, CRF 18, AAC 160 kb/s, faststart, bitexact flags, metadata stripped.
6. Verify output: h264, aac at $R$, duration within 0.1 s of $T_N$. Store video and subtitles blobs, then the `Manifest`.

11.3 Subtitles. Words are grouped greedily into cues, closed at a word ending in `. ? ! ; :`, before exceeding 84 characters, or before spanning 6 s; cues longer than 42 characters wrap once at the space nearest the middle; text is HTML-escaped. The global VTT is built here, since only assembly knows $T_i$.

11.4 Manifest. `artifacts` = {`storyboard`, `render/<id>`, `narration/<id>`}; `versions` = {`assemble`, `ffmpeg`}; `timings_s.assemble`; `metrics` = {`duration_s` $=T_N$, `loudness_in_lufs`, `true_peak_in_dbtp`} (input, pass 1). `usage` is zero; the orchestrator adds stage usage.

11.5 Notes. Clip audio is ignored; narration is the only audio. Output bytes are reproducible for fixed inputs, ffmpeg build and $p$; $p$ changes x264 output, hence in $k$. Requires `ffmpeg`, `ffprobe` (apt `ffmpeg`, with libx264). Blobs are passed to ffmpeg by store path (content-probed); only the output uses a temporary directory, removed on exit.

## 12 Orchestration and evaluation

12.1 Interface. `pipeline.Pipeline(settings, llm, tts, verbalizer, animate, fetch, check)`; `run(bundle, edit=None, part=None) -> Manifest | Paused`. One method per stage takes and returns artifacts; `animate` has the WP8 signature `(scene, data, narration, store, llm, params) -> (SceneRender, Usage)`, default `render_only` (primitive library, §9) until `scene.animate` lands. `tts(params)` defaults to `voice`: Kokoro at `$ANIMATH_KOKORO`, else espeak-ng; `voice = default` keeps the backend default.

**Algorithm 12.1 (run).**
1. $\mathcal D = \Phi_1(\mathcal S)$; if `part`, restrict $\mathcal D$ (Algorithm 12.2).
2. $\mathcal K = \Phi_2(\mathcal D)$; gate (§12.3).
3. $\mathcal B = \Phi_3(\mathcal K, \pi)$ with `scene.catalog()` and kernel schemas; gate.
4. $\Phi_4 \parallel \Phi_6$ on two threads; each uses `workers` threads.
5. $\Phi_5$ per scene, cached under
$$k_s = d\big([\texttt{animate}, v, f, d(s), d(N_s), d(\pi_5), d(D_{s,1}), \dots]\big), \tag{12.1}$$
$f$ the animate function's qualified name, $\pi_5$ = (`width`, `height`, `fps`, `style`, `seed`, `max_retries`), $D_{s,i}$ the scene's datasets by request digest. Misses run in a `spawn` process pool of $\min(p, \#\text{misses})$ workers (render is thread-unsafe); inline if $p = 1$ or one miss. Workers rebuild store and LLM from `Settings`; returned usage is summed with that of $\Phi_1$–$\Phi_3$.
6. $\Phi_7$; the manifest gains `source`, `doc`, `graph`, `dataset/<request>` digests, stage versions and model, stage timings, summed usage, automatic metrics (§12.5); it is stored and returned.

12.2 Selection. `bundle(path, params, store, pages)`: a PDF alone, MD with sibling `.bib`, LaTeX with its tree (`.tex .bib .bbl .sty .cls`, hidden paths skipped). `pages("3-7,9")` copies the 1-based pages by pdfium and fixes the random trailer `/ID` to $d(\text{bytes}, \text{indices})$, so the bundle digest is reproducible (N2).

**Algorithm 12.2 (section).** Path components split by `/`; a component `2.3.1` expands to ordinals $2, 3, 1$, any other is a case-folded title substring. Start with all blocks. For each key: among headings strictly inside the current range, take those of minimal level; pick the $k$-th or the first matching title; the range becomes that heading up to the next heading of the same level. Refs to labels outside the range are dropped (bibliography kept); title $=$ document title and chosen headings joined by `/`. No match raises `PipelineError`.

12.3 Gates (F12). With `approval_gates`, after $\Phi_2$ and $\Phi_3$ the artifact $a$ is looked up under $k = d([\texttt{gate}, \text{kind}, d(a)])$ in namespace `gate`; a hit continues with the approved digest, which may name an edited artifact. A miss returns `Paused(kind, d(a))` unless `edit` is given: `''` approves $a$, JSON text approves the validated replacement; one `edit` serves one gate. Every stage is cached, so resuming re-runs nothing.

| Step | CLI |
|---|---|
| review $\mathcal K$ | `animath run src` → `{"paused": "graph", "digest": d}`; `animath inspect graph d` |
| approve | `animath run src --approve`, or `--edit graph.json` |
| review, approve $\mathcal B$ | same, kind `storyboard` |

12.4 Budget (N9). After each LLM stage the summed usage $u$ costs $c = p\cdot u / 10^6$ USD with per-MTok prices $p$ (input, output, cache read, cache write) from `PRICES` (`claude-opus-5-5`: 4, 20, 0.2, 5). $c >$ `budget_usd` raises `PipelineError`; a model without prices raises when a budget is set.

12.5 Metrics (SPEC §5), `eval.metrics`, `eval.formula`, `eval.judge`; `eval.evaluate(store, manifest, expected, llm)` reads every input from the manifest.

| Metric | Definition | Source |
|---|---|---|
| $Q_1$ `q1_render` | fraction of renders with `checks.render` | automatic |
| $Q_2$ `q2_fidelity` | fraction of reference equations (by label, else position) whose normalized LaTeX matches | `--expected` |
| $Q_3$ `q3_sync_ms` | $10^3\max_{s,b}\lvert t^R_{s,b} - t^N_{s,b}\rvert$ | automatic |
| $Q_4$ `q4_layout` | failed `layout`, `critic` checks per scene | automatic |
| $Q_5$ `q5_coverage` | §6.3 | automatic |
| $Q_6$ `q6_duration` | $\lvert T_N - T\rvert / T$ | automatic |
| $Q_7$ `q7_pedagogy` | mean of the 4 rubric scores (1–5) of the judge on storyboard, source equations, 8 keyframes (768 px, $t_j = (j+\frac12)T/8$) | `--judge` |
| $N_1$ `n1_traced` | fraction of on-screen formulas traced (Algorithm 12.3) | automatic |

`metrics.failures` lists metrics missing their target (`TARGETS`).

**Algorithm 12.3 (equivalence, N1, I2).** Normalization: drop spacing and sizing commands (`\,`, `\quad`, `\left`, `\big`, …), tokenize into control words, control symbols and characters, unwrap single-token script braces, strip trailing `.,;`; compare token sequences. Equivalence: parse by SymPy `parse_latex` (Lark backend, font commands removed); an ambiguous parse yields all readings; equalities $a = b$, $c = d$ agree iff $(a-b) \mp (c-d)$ simplifies to 0, expressions iff $a - b$ does. Verdict: True if some pair agrees, False if none, None if either side does not parse. Formulas shown are `math`, `equation` latex and `derive` steps (match markers removed). A formula is traced iff it matches an equation of $\mathcal D$ (normalized or equivalent), or, as a derive step, is equivalent to its predecessor.

12.6 Golden run (C5). Requires `ANIMATH_API_KEY` (§2.3) as an environment variable. For each case: `animath run <source> -p approval_gates=false`, then `animath eval <manifest> --expected tests/golden/<case>/expected.json --judge`.

12.7 Decisions.

| # | Decision | Reason |
|---|---|---|
| E1 | Section and page selection in the orchestrator, not in ingestion | DocIR and PDF slicing suffice; no contract change |
| E2 | Gate approvals keyed by the produced artifact digest | stages are cached, so the key is stable; edits are plain artifacts |
| E3 | $\Phi_5$ in spawned processes | Manim and VTK globals; `fork` after threads is unsafe |
| E4 | SymPy verdict is three-valued | Lark grammar covers a subset of LaTeX; unparseable is not wrong |
| E5 | $Q_7$ from storyboard and keyframes, not audio | narration text is in the storyboard; frames carry layout |

12.8 Performance (4 cores): `tests/test_pipeline.py` ≈ 16 s; real two-scene 320×240 render through the pool ≈ 7 s including two interpreter spawns.
## 13 Performance metrics

| Item | Value |
|---|---|
| `make check` wall time (WP0) | ≈ 5 s on 4 cores |
| `make check` wall time (WP5) | ≈ 12 s on 4 cores |
| Assembly, 3 × 10 s 1080p60 clips, $p=4$ | 34 s (1.15 × real time) |
| Numerics, largest admissible request per kind | rule convergence 0.8 s; EFIE $ka=50$, $n=2048$ 2.3 s; DLP $n_{\max}=1024$ 3.8 s; GMRES $n=1024$, $m=256$ 1.2 s; CG $n=1024$ 0.4 s |
| `make check` wall time (WP3) | ≈ 30 s on 4 cores |
| Draft render, 12 s scene, 8 primitives (`surface` included) | ≈ 10.5 s on 4 cores |
| `tests/extract` | ≈ 2 s on 4 cores |
| `tests/scene` WP8 part | ≈ 10 s on 4 cores |

## 14 Decisions log

| # | Date | Decision | Reason |
|---|---|---|---|
| D1 | 2026-10-07 | Code in GitHub `kleasama/animath`; Drive holds documents only | parallel WPs need a git remote |
| D2 | 2026-10-07 | C0 defaults accepted (SPEC §8) | user approval |
| D3 | 2026-10-07 | CPU-only toolchain; GPU parsers replaced by Claude vision transcription | no GPU in containers |
| D4 | 2026-10-07 | Schemas frozen at C1; changes only through integrator | parallel WPs without conflicts |
| D5 | 2026-10-07 | Commits authored by the user, no co-author trailers | user preference |
| D6 | 2026-10-07 | `requirements.lock` instead of `uv.lock` (177 kB) | Drive transfer size |
| D7 | 2026-10-07 | Numerics in NumPy/SciPy without Numba | largest admissible request < 4 s; `hankel2` has no Numba support |
