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

2.3 Settings (`core.config.Settings`): defaults, then TOML file (`--config`), then `ANIMATH_<FIELD>` variables. Fields: `store`, `model`, `effort`, `max_tokens`, `workers`, `offline`, `llm` (`api` or `session`). Online, the API key is `ANIMATH_API_KEY`, else `ANTHROPIC_API_KEY` (reserved in cloud environments); none raises `LLMError`.
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
4.2 `Claude`: `beta.messages.stream` with `output_format=schema`, read by `get_final_message` (the SDK refuses non-streaming requests whose `max_tokens` may exceed 10 min, e.g. the default 32000), ephemeral cache on the system prompt, PNG images first, `output_config.effort`, server-side refusal fallback (`fallbacks="default"`). Any `stop_reason` other than `end_turn`, and output failing the schema (e.g. truncated at `max_tokens`), raise `LLMError`.
4.3 `Replay`: key $d([t, \text{JSON schema}, \text{system}, \text{prompt}, [d(\text{image}_i)]])$; hit returns cached instance with zero usage; offline miss raises `LLMError`. Unit tests run offline.
4.4 Provenance tag $t$ (`llm.tag`): `session`, else `model:effort`; also `Manifest.versions["model"]`.
4.5 `Session` (`llm = session`): requests answered out of band, e.g. by a Claude Code session. A miss writes `<store>/pending/<key>/request.json` (JSON schema, system, prompt, image files `<i>.png`) and raises `PendingError`; `animath` then prints `{"pending": [dirs]}` and exits 0. A rerun reads `<key>/answer.json`, validates it against the schema (invalid raises `LLMError`) and caches it through `Replay`. Usage is zero.

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
| other `Div` with id (e.g. labelled `table`) | its blocks; the first unlabelled one takes the id as label |
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
5. Expand `\newcolumntype` letters in `tabular`/`array`/`longtable` column specs (pandoc ignores them); replace `algorithm`/`algorithmic` environments by tokens; text = caption, then algorithmic(x) steps, one per line, indented by nesting.
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
| `h2.rss` | `geometry` ∈ {plate, sphere}, `n`, `leaf`, `eta`, `kappa`, `tol`, `precision` ∈ {single, double}, `seed` | `points`, `perm`, `box`, `range`, `near`, `far`, `dof` (CSR, with `_ptr`), `stage`, `stage_norm`, `dag`, `schur`, `schur_norm`, `fill`, `fill_norm`, `active`, `top` | `depth`, `top_level`, `top_size`, `colours`, `stages`, `error` |
| `data.npz` | `path` (absolute, `.npz`), `sha256` | the archive's numeric members | its 0-d `meta` member, a JSON object |

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

8.8 Strong recursive skeletonisation (`h2.rss`). Points: a plate, the $m \times m$ cell centres of the unit square ($n = m^2$, $w = 1/n$), or a sphere, the Fibonacci lattice on the sphere of radius $\tfrac12$ centred in the unit cube ($w = \pi/n$). With $G(r) = e^{i\kappa r}/(4\pi r)$ and $\square_i$ the square of side $\sqrt w$ centred at $x_i$,
$$A_{ij} = w\,G(|x_i - x_j|)\ (i \ne j),\qquad A_{ii} = \int_{\square_i} G(|y|)\,dy = \frac14\sum_{q=1}^{16} c_q\,\frac{e^{i\kappa\rho_q} - 1}{i\kappa},\quad \rho_q = \frac{\sqrt w}{2\cos\theta_q}, \tag{8.7}$$
$\theta_q = \tfrac\pi8(u_q + 1)$, $(u_q, c_q)$ the 16-point Gauss–Legendre rule; $\kappa = 0$ gives $A_{ii} = \sqrt w\,\ln(1+\sqrt2)/\pi$. The factorisation runs in `precision` (complex64 by default, real when $\kappa = 0$), with `tol` $\ge 10\epsilon$ of that precision.

Cluster tree: balanced binary of depth $d = \min\{d : \ell\,2^d \ge n\}$, $\ell$ = `leaf`, numbered breadth-first with children $2t+1, 2t+2$; each split is at the rank median along the axis minimising the larger child diameter (first minimiser); $[l_t, h_t]$ is the tight bounding box, $\operatorname{diam} t = |h_t - l_t|$. Lists, level by level from $N(0) = \{0\}$, with $C(t) = \operatorname{ch} N(\operatorname{pa} t)$ and $\delta$ the box distance:
$$F(t) = \{s \in C(t) : \delta(t,s) > 0,\ \tfrac12(\operatorname{diam} t + \operatorname{diam} s) \le \eta\,\delta(t,s)\},\qquad N(t) = C(t) \setminus F(t). \tag{8.8}$$
Every pair of leaves lies in exactly one block $t \times s$ with $s \in N(t)$ at level $d$ or $s \in F(t)$ at some level. Level $\lambda$ is coloured greedily in tree order,
$$c(t) = \min\{c \ge 0 : c \ne c(u)\ \forall u \in N^2(t),\ u < t\},\qquad N^2(t) = \textstyle\bigcup_{s \in N(t)} N(s), \tag{8.9}$$
so stages of one colour touch disjoint neighbourhoods and may run in parallel. Stage order is (colour, tree index); the DAG has an edge from each stage to every later stage in $N^2(t)$.

Column ID by pivoted QR $M P = Q\begin{bmatrix} R_{11} & R_{12} \\ 0 & R_{22}\end{bmatrix}$, $S$ the first $k$ pivots, $R$ the rest, $\varepsilon$ = `tol`:
$$k = \#\{j : |r_{jj}| > \varepsilon\,|r_{11}|\},\qquad T = R_{11}^{-1}R_{12},\qquad \|M_{:,R} - M_{:,S}T\|_F = \|R_{22}\|_F. \tag{8.10}$$

**Algorithm 8.3 (strong RS-S).** Active DOFs $B_t$ (the leaf's indices at level $d$), near blocks $D_{ts} = A_{B_t B_s}$, no fill $\Phi$. Top level $\tau = \lambda_F - 1$, $\lambda_F$ the coarsest level with a far pair ($\tau = d$ if there is none). For $\lambda = d, \dots, \tau + 1$ and $t$ in stage order:
1. Far field $K_{BF} = [A_{B_t B_s} + \Phi_{ts}]_{s \notin N(t)}$, $K_{FB}$ likewise; ID (8.10) of $\begin{bmatrix} \mathrm R(K_{FB}) \\ \mathrm R(K_{BF}^{T}) \end{bmatrix}$, $\mathrm R(\cdot)$ the thin-QR triangle (same pivots and $R_{ij}$ as the full far field).
2. Shear rows $X_R \leftarrow X_R - T^{T}X_S$ and columns likewise in $D_{tt}$, $D_{ts}$, $D_{st}$: the far couplings of $R$ vanish up to (8.10).
3. LU of $\tilde A_{RR}$; with $J = S \cup \bigcup_{s \in N(t)\setminus t} B_s$, $L_{21} = \tilde A_{JR}\tilde A_{RR}^{-1}$, $U_{12} = \tilde A_{RR}^{-1}\tilde A_{RJ}$.
4. Schur update
$$\tilde A_{JJ} \leftarrow \tilde A_{JJ} - L_{21}\tilde A_{RJ}; \tag{8.11}$$
block $(a, b) \in N(t)^2$ adds to $D_{ab}$ if $b \in N(a)$, else to the fill $\Phi_{ab}$. Then $B_t \leftarrow B_t(S)$.

After each level $B_p = B_{2p+1} \cup B_{2p+2}$; $D_{pq}$, $q \in N(p)$, is assembled from the child near blocks and, for far child pairs, $A$ plus their fill; the remaining fill moves to the parents. Finally, dense LU of $[D_{pq}]$ on level $\tau$. Solve: forward sweep (shear, $L_{21}$, $\tilde A_{RR}^{-1}$), top solve, backward sweep in reverse ($U_{12}$, $T$). The reported error is $\|\tilde x - x\|/\|x\|$ with $x = A^{-1}g$ by dense complex128 LU and $g$ complex Gaussian from `seed`. A singular pivot block raises `ComputeError`.

Trace: `stage` rows $(t, \lambda, c(t), n_t, k_t, r_t, |J|)$; `stage_norm` $(\|K_{BF}\|_2, \|K_{FB}\|_2, \|R_{22}\|_F)$; `schur` rows (stage, $a$, $b$, fill) with $\|\Delta\|_F$ in `schur_norm`; `fill` rows $(\lambda, a, b)$, the fill entering level $\lambda$, with norms; `active` $(\lambda, \sum_t |B_t|)$ at the start of each level and at the top; `dof` per stage $[B_t(S), B_t(R)]$; `top` the top DOFs.

Instance $n = 4096$, `leaf` 64 ($d = 6$), $\eta = 2.5$, $\kappa = 2\pi$, complex64: top level 2, colours 12, 10, 9, 6 on levels 6–3.

| `tol` | $r_t/n_t$, leaves | active, levels 6 → 2 | error |
|---|---|---|---|
| 1e-3 | 0.70–0.88 | 4096, 844, 550, 251, 130 | 1.7e-4 |
| 1e-4 | 0.56–0.78 | 4096, 1275, 818, 378, 192 | 1.9e-5 |
| 1e-5 | 0.39–0.72 | 4096, 1768, 1148, 507, 264 | 2.3e-6 |

Implementation: GEMMs go through SciPy's BLAS (`get_blas_funcs`), since the NumPy and SciPy wheels bundle separate OpenBLAS builds whose thread pools contend when calls interleave (about 8× slower); 2-norms of tall blocks come from their thin-QR triangles; the reference matrix is assembled in 512-row slabs.

8.9 File-backed data (`data.npz`). The archive is read once and its SHA-256 must equal `sha256`, so the key (8.1) pins the content and later runs need no file. Members load with `allow_pickle=False`; a mismatch, an unreadable archive, a non-numeric member or a `meta` that is not a JSON object raises `ComputeError`. The kind brings arrays computed elsewhere (for example by the user) into scenes; its schema tells the planner not to invent it.

## 9 Scenes and rendering

Algorithm 9.1 Scene generation: SPEC Algorithm 6.1.

9.1 Modules. `scene.layout` (geometry, no Manim), `scene.primitives` (registry `PRIMITIVES`, `catalog()` of argument JSON schemas), `scene.render` (`timeline`, `compose`, `schedule`, `render`).

9.2 Primitives. A `Visual` names a primitive and carries its arguments; every argument model extends `Args` with `region` (default `main`) and `until` (bookmark that removes the visual). Numerical arguments are literals or `ArrayRef` $(i, a)$: array $a$ of the `DataSet` answering `scene.data[i]`, stored as one `.npy` blob and loaded with `allow_pickle=False`. Complex arrays must select `part` $\in$ {`abs`, `real`, `imag`} wherever a real array is drawn (`plot`, `field`, `surface`); `matrix` takes complex input directly.

| Primitive | Arguments | Visual | Cues |
|---|---|---|---|
| `text` | `text` (LaTeX text mode) | `Tex` | write |
| `equation` | `latex` | `MathTex` | write |
| `derive` | `steps` ($\ge 2$; `{{...}}` marks matched parts) | `MathTex` chain | write, then `TransformMatchingTex` at $t_0 + k(t_1-t_0)/n$ |
| `matrix` | `entries` (strings or `ArrayRef`) | entries if $\max(m,n) \le 8$, centred on a grid whose pitch clears the largest entry by 0.4; else heatmap of $\log_{10}\lvert a_{ij}\rvert$ | write or fade in |
| `plot` | `series` ($\le 5$; `x`, `y`, `label`), `xlabel`, `ylabel`, `logy` | `Axes`, line graphs, legend | write |
| `field` | `values` $u_{ij}$ at $(x_j, y_i)$, $y$ upward | viridis heatmap | fade in |
| `surface` | `points` $(n,3)$, `faces` $(m,3)$, `scalars` $(n)$ or $(m)$, `azimuth`, `elevation` | PyVista offscreen image | fade in |
| `trace` | `lines` (plain text, not TeX), `steps` (line indices) | monospace listing, cursor | write, then cursor to line `steps[i]` at $t_0 + i(t_1-t_0)/n$ |
| `hierarchy` | `data`, `level`, `done`, `coloured`, `views` ⊆ {`plate`, `operator`}, `steps` (`do`, `part`) | cluster boxes; block operator in tree order (§9.15) | fade in, then step $i$ at $t_0 + (i+1)(t_1-t_0)/(n+1)$ |

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

9.11 Localization. Every error names visual $i$ of scene $s$ as `s.i:primitive` (render, gate and critic alike). `repair` may replace only the visuals named in $E$ (block level; snippet line numbers give line level), else all visuals (scene level). The model returns `Patch` = [(index, primitive, args as JSON string, at)]; a patch outside the allowed indices, with non-object `args`, or yielding an invalid `Scene` is rejected. The prompt carries goal, narration, math, data requests, indexed visuals, $E$, allowed indices and pitfalls; the system prompt carries the catalog (with `code`), region sizes and the pinned API (constructor parameters, at most 8 per class), so it is cached. Patches are memoized in namespace `repair` under $H(\text{system}, s, E)$: pitfalls are advisory and change between runs, so they stay out of the key and a resumed run replays its repairs.

9.12 Critic. Moving frames are those within 1 s after an entry or a `derive` step ($t_0 + k(t_1-t_0)/n$, $k \ge 1$) and within 0.5 s before an exit. Keyframes: for consecutive change frames $a < b$ of the visual set or of a `derive` step,
$$n = \max\{\, m \in [a, b) : m \text{ not moving} \,\}, \tag{9.6}$$
kept if it exists and a visual is alive; at most 6, evenly subsampled. A transient state with no still frame is skipped. A visual alive at $n$ fails if its grid cell has no pixel above 16 (of 255). Only if no visual fails, the model receives the keyframes as PNG with the plan and returns `Verdict` (issues with optional visual index).

9.13 Pitfall memory. Index namespace `pitfall`, key $H(\text{primitive})$ (`scene` for unlocalized errors), value a blob with the last 8 distinct messages (300 characters each). Read-modify-write is last-writer-wins across processes; a lost entry only weakens a hint.

9.14 Notes.
1. `animate` registers `code` in `PRIMITIVES` for its duration; with the renderer this makes it thread-unsafe: parallelize scenes over processes (WP9). `scene.catalog()` stays free of `code`, so the planner never emits it.
2. LaTeX precompile is the build phase of the draft render: `compose` builds every mobject before any frame, and build errors are localized.
3. Unit tests use a queued fake LLM (`tests/scene/fake.py`); no network.

9.15 `hierarchy` primitive. Draws an `h2.rss` DataSet (§8.8) from level $\lambda$ (default $d$, `done` stages already eliminated). Plate view (2-D points only): cluster boxes, grey or in their colour class, with a $k_t \mid r_t$ bar from split to eliminate (the $r_t$ part white once zeroed), dimmed once eliminated. Operator view: the active matrix in tree order, block widths $\propto |B_t|$, rescaled to the full side on each level; near blocks orange, far blocks blue by level (darker is coarser, the background is the far field of level $\lambda$), fill amber, zeroed bands white, $S$ blue and $R$ red. Parts, as `Part` fields or selectors: `t` (the first stage of the level with the largest $|N(t)|$), `s` (its next later neighbour), `cluster:k` (BFS id), `colour:c`, `block:a:b` (also `block:a,b`). `verbs`, `part` and `act` expose the verbs and parts to word-timed actions.

| Action | Effect |
|---|---|
| `select`, `footprint`, `ring` | mark $t$ (exclusive), $N(t)$, $N^2(t) \setminus N(t)$ (dashed) |
| `clear`, `colour` | unmark $t$ or all; colour $t$, a colour class or the level by $c(t)$ |
| `rotate`, `split`, `zero`, `eliminate`, `schur`, `fill` | phases 1–6 of stage $t$, monotone: flash its rows and columns; split $S \mid R$; zero $R$ against the far field; shrink to $k_t$; flash $N(t)^2$; show its fill |
| `drop` | remove a fill block on view, flashing it (at least 0.3 wide) and the boxes of its pair |
| `wave` | eliminate the pending stages of a colour (default the least), flashing the class |
| `coarsen` | finish the level and merge children into parents |
| `top` | one dense block on the top level |

`advance` maps (state, step) to the next state and its flashes, and rejects a part kind the verb does not take (`TAKES`: cluster parts by default; `colour` cluster or class; `wave` class; `drop` block; `coarsen` and `top` none). `draw` maps a state to keyed specs. The `Board` holds the current state; `go(steps)` advances it and returns one `AnimationGroup` of one `Transform` per changed key, whose group is the board itself, already in the scene, so `Scene.add` leaves it whole. A vanishing near or fill block morphs into its parent's fill or near block (else the dense top), a box into its parent box; anything else fades; flashes run there and back. Items are created invisible on first use and removed at the next transition; an invisible anchor recovers the fit (9.2). `steps` are cues at $t_0 + (i+1)(t_1-t_0)/(n+1)$, and steps closer than 0.1 s raise `AnimateError`; actions call `go` when they play. Steps and actions thus advance one state in play order, and a continued view replays its actions at build; a resumed view replays its steps before its actions, so a visual takes one or the other. Selectors resolve when the verb plays, against the current level. For the generic verbs, `part` returns a group of the items a selector names (the boxes of its clusters on the plate, else their diagonal blocks; the block), a child of the board refilled after every transition, so a part follows the walk across levels.

## 10 Narration

10.1 $\Phi_6$ maps each scene $s$ with lines $\ell_1,\dots,\ell_m$ to a `Narration`: audio, duration, spoken `words` and written `captions` with times, bookmark times. Entry: `narrate.narrate(board, store, tts, verbalizer, workers) -> {scene id: digest}`.

| Module | Content |
|---|---|
| `verbalize` | split prose and inline math (`$…$`, `$$…$$`, `\(…\)`); `TEX` rewrites → MathML (MathJax 3.2.1) → speech (SRE 4.1.4, ClearSpeak) → `SPEECH` rewrites (§10.6), one `node sre.cjs` call per stage run; source tokens as (written, spoken) pairs (§10.6) |
| `written` | inline TeX → compact Unicode for captions (§10.6) |
| `g2p` | spoken forms, espeak-ng IPA mapped to the misaki inventory, per-word alignment (Algorithm 10.2) |
| `tts` | `TTS` protocol (`id`, `rate`, `synth(text) -> (int16 PCM, word spans)`); `Kokoro`, `Espeak`; WAV I/O |
| `align` | sentence timeline: trim, fades, gaps, word and bookmark times (Algorithm 10.3) |
| `proc` | subprocess call with typed failure |

10.2 Runtime requirements: `espeak-ng` on `PATH`; `NODE_PATH` holding `speech-rule-engine@4.1.4` and `mathjax-full@3.2.1`; for Kokoro, `ANIMATH_KOKORO` naming a directory with the files below. Hugging Face is unreachable from the build containers; GitHub release assets are reachable. Weights are never committed.

| File | Source | SHA-256 |
|---|---|---|
| `kokoro-v1.0.onnx` | release `model-files-v1.0` of `thewh1teagle/kokoro-onnx` | `7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5` |
| `voices-v1.0.bin` | same release; npz, voice $\to 510\times1\times256$ float32 | `bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d` |
| `config.json` | `src/kokoro_onnx/config.json` of the same repository; key `vocab` (114 symbols) | `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f` |

| Backend | Rate | Default | Status |
|---|---|---|---|
| `Kokoro` (SPEC Q6) | 24 kHz | voice `af_heart`, speed 0.85 | verified with the weights above |
| `Espeak` (no `ANIMATH_KOKORO`) | 22.05 kHz | `en-us`, 140 wpm | verified; last resort |

Other voices of the file: `am_michael` (US), `bf_emma`, `bm_george` (GB; prefix `b` selects `en-gb` phonemes), and the rest of the Kokoro v1.0 list. The `voice` parameter selects one (§12.1).

10.3 Cache key. With $v$ the stage version,
$$k = d\big(["\text{narrate}", v, d(\text{id}, \text{narration}), \text{tts.id}, \text{verbalizer.id}]\big). \tag{10.1}$$
`tts.id` = `kokoro:` model SHA-256 prefix, voice, speed, $d$(lexicon, word list, phoneme map, vocab, voice style); `verbalizer.id` = `sre:` domain, $d$(`TEX`, `SPEECH`). Edits to visuals, math or duration of a scene do not trigger re-synthesis; edits to any pronunciation table do. `written` and the `align` constants are covered by $v$.

10.4 Sentences. Lines are joined until one ends in `.`, `!` or `?` (closing quotes and brackets allowed after it); each sentence is one `synth` call, so intonation runs across line boundaries. A bookmark is the index of its line's first word within the sentence.

**Algorithm 10.1 (Kokoro synthesis).** Input: words $w_1,\dots,w_n$ of a sentence.
1. Phonemes $p_i$ by Algorithm 10.2. Leading and trailing punctuation $o_i, c_i$ of $w_i$ stays in the token stream (`;:,.!?—…"()“”`): Kokoro renders it as pauses and intonation.
2. Tokens $t = o_1 p_1 c_1 \sqcup \dots \sqcup o_n p_n c_n$, $\sqcup$ the space id. If $\lvert t\rvert > 510$, split recursively at the clause end nearest the middle of the token count.
3. Run the graph on $[0, t, 0]$ with style row $S_{\text{voice}}[\lvert t\rvert - 1]$ and speed $\sigma$. The graph also outputs `/encoder/Clip_output_0`, the duration $\delta_j \ge 1$ of input token $j$ in frames of $h = 600$ samples; the audio has $h\sum_j \delta_j$ samples.
4. With $F_j = h\sum_{k<j}\delta_k$ and $[a_i, b_i)$ the token range of $p_i$ in $t$, word $i$ spans samples
$$\big[F_{a_i+1},\; F_{b_i+1}\big), \tag{10.2}$$
the shift by one accounting for the leading pad token.
5. Scale by $\frac12$ (raw peaks reach full scale), round to int16.

The extra output is added by editing the serialized `ModelProto` (field 7 graph, field 12 output, `ValueInfoProto` name field 1); no `onnx` dependency.

**Algorithm 10.2 (phonemes, `g2p.Phonemizer`).**
1. Spoken core of each word, punctuation split off: lexicon entries as espeak mnemonics (*Schur* `[[S'Ur]]`, *Galerkin*, *Lanczos*, …); 2–4 capitals or hyphenated capitals spelled (*LU* → L U, *RS-S* → R S S; *BLAS*, *NASA*, *RAM*, *SIAM* read as words); the letter *A* before an operator word, a single letter or the end `[['eI]]`.
2. Clauses: maximal runs of words without inner punctuation. In-context IPA $c$ of each clause: one `espeak-ng --ipa --tie=^` call, mapped to the misaki inventory (`COMMON | E2M[lang]`, longest match first).
3. Stand-alone IPA $s_1,\dots,s_n$ of all cores: one call, one core per line, `-l 4096` (every line a clause); stress marks dropped. A line count other than $n$ raises `NarrateError`.
4. espeak joins function words (*from the* → `fɹʌmðə`, *for a* → `fəɹɹə`) and expands numbers, so $c$ has no one-to-one word split. Align $b = s_1 \sqcup \dots \sqcup s_n$ with $c$ stripped of stress marks (`difflib.SequenceMatcher`, no autojunk). The separator after $s_i$ maps through the opcode containing it: exactly for `equal`, proportionally for `replace`, to the opcode start for `delete`. $c$ is cut there; a stress mark at a cut goes to the following word.

$p_i$ is the in-context pronunciation of $w_i$, non-empty for every pronounced word, so (10.2) gives every word a positive span.

**Algorithm 10.3 (timeline, `align.timeline`).** Rate $r$; sentences $k = 1,\dots,K$ with PCM $x_k$ and spans (10.2).
1. Bounds $[a_k, b_k)$: first to last 10 ms frame with RMS above $-60$ dBFS, widened by 50 ms, clamped; a silent sentence raises `NarrateError`.
2. Raised-cosine fades of $m = 0.01r$ samples at both ends, gain $\frac12 - \frac12\cos\big(\pi (j+\frac12)/m\big)$, $j < m$.
3. Layout: $L = 0.3$ s silence, each faded sentence followed by $G = 0.4$ s, the last gap replaced by $T = 0.6$ s. Offsets $o_1 = Lr$, $o_{k+1} = o_k + b_k - a_k + Gr$.
4. Word times $\big(o_k + \operatorname{clip}(\text{span}, a_k, b_k) - a_k\big)/r$; a bookmark is the start of its word.

Duration $= L + T + (K-1)G + \sum_k (b_k - a_k)/r$. Silence between sentences is $G$ plus both pads, ≈ 0.5 s; within a sentence only the model's own pauses occur.

10.5 Accuracy. Word times are the model's token durations, exact to one frame (25 ms); bookmarks are word starts, so $Q_3$ holds by construction. Measured on the §2.8 test narration (11 scenes, 789 words, `af_heart`, speed 0.85): 140 wpm overall, 151 wpm within sentences; Whisper base.en (offline) transcribed 92.7 % of the words verbatim, the rest spelling variants (*colour*, numerals).

10.6 Math speech and captions. `TEX` rewrites before SRE: `\mathcal H^2` → H two; two-digit subscripts spaced; upright superscript words read as words. `SPEECH` rewrites after SRE turn ClearSpeak into lecture style: powers $-1$, $T$, $-T$, $*$, $H$ → inverse, transpose, inverse transpose, star, Hermitian; *raised to the k power* → to the k; fractions and *divided by* → over; *the metric of x sub 2* → the 2 norm of x; *script l* → ell; *O of* → order; font words, parentheses and *sub* dropped; *comma dot dot dot comma* → up to; *negative* → minus; *is a member of* → in.

| TeX | Spoken | Caption |
|---|---|---|
| `L_{21}`, `D_{RR}`, `\mathcal N(t)` | L 2 1, D R R, N of t | L₂₁, D_RR, 𝒩(t) |
| `\epsilon_L/u`, `\chi/(1-\chi)` | epsilon L over u, chi over 1 minus chi | ε_L/u, χ/(1−χ) |
| `\mathcal H^2`, `\|A^{-1}\|_2` | H two, the 2 norm of A inverse | ℋ², ‖A⁻¹‖₂ |

Captions show what is written, speech what is said. `Verbalizer.tokens` splits each line at prose whitespace into source tokens $\tau_1,\dots,\tau_q$, a formula with the punctuation touching it being one token, each with its written and spoken form. The written form of a formula is `written(tex)`, a recursive descent over TeX tokens: Greek letters and operators as symbols; `\mathcal`, `\mathbb` letters; sub- and superscripts in Unicode when every character has one and the script is no word of three or more letters, else `_max`, `_(i,j)`; `\frac{a}{b}` as $a/b$, compound parts parenthesized; accents as combining marks; relations spaced; `\left`, `\right`, fonts and environments dropped; other commands kept by name. With $n_j$ spoken words in $\tau_j$ and $N_j = \sum_{i\le j} n_i$, caption $j$ spans
$$\big[\text{start}(w_{N_{j-1}+1}),\; \text{end}(w_{N_j})\big], \tag{10.3}$$
so a caption boundary is a token boundary; tokens with no spoken word are dropped. `words` keeps the spoken words (bookmarks, $Q_3$); `captions` feeds the subtitles (§11.3).

10.7 Concurrency. Scenes run on a thread pool of `workers`; formulas of all uncached scenes are verbalized in one subprocess before the pool starts; the ONNX session is shared (thread-safe `run`) with `intra_op_num_threads` fixed for determinism.

10.8 Deviations from SPEC §6.3. No forced alignment (torchaudio): the duration output gives token times directly, `forced_align` is deprecated, and torch would dominate the image.

10.9 Measurements (4 cores): Kokoro load ≈ 6 s (325 MB model read and edited); the 789-word narration (340 s of audio) synthesizes in 186 s with 4 threads; Espeak, two lines with three formulas: cold 0.74 s.

## 11 Assembly

11.1 Interface. `assemble.assemble(store, board, renders, narrations, threads=1) -> str` maps the digests of a `Storyboard`, its `SceneRender`s and `Narration`s (any order, matched by `scene_id`) to the digest of a `Manifest`. Key $k = d([\texttt{assemble}, v, p, d_{\mathcal{B}}, d^R_1,\dots,d^R_N, d^N_1,\dots,d^N_N])$ in scene order, $p$ = threads; hit $\Rightarrow$ no work.

11.2 Timeline. Scene $i$ has render duration $d^R_i$, narration duration $d^N_i$, frame rate $f$ (common to all clips), audio rate $R = 48$ kHz. With $d_i = \max(d^R_i, d^N_i)$,
$$n_i = \lceil f d_i - 10^{-6} \rceil,\qquad T_i = \frac{1}{f}\sum_{j<i} n_j,\qquad S_i = \operatorname{round}(R\,T_{i+1}) - \operatorname{round}(R\,T_i). \tag{11.1}$$
Segment $i$ is exactly $n_i$ frames and $S_i$ samples; $\sum_i S_i = \operatorname{round}(R\,T_{N})$, so audio–video drift is below one sample for any $N$. Subtitle cue times are word times plus $T_i$.

**Algorithm 11.1 (assemble).**
1. Load artifacts; require renders and narrations to cover the storyboard scenes bijectively.
2. Probe clips: equal width, height, $f$; $\lvert \text{probe} - \text{claimed}\rvert \le 0.1$ s for every clip and audio.
3. Compute (11.1); build WebVTT (§11.3).
4. Loudness pass 1: concatenate trimmed narration; `loudnorm` measures integrated loudness $I$ (EBU R128) and true peak; silent narration is an error.
5. Pass 2, one `ffmpeg` call: per clip `fps`, `tpad` (clone last frame), `trim` to $n_i$; per narration resample to $R$ mono, `apad`, `atrim` to $S_i$; `concat`; gain $-16 - I$ dB, then `alimiter` (ceiling $-2.5$ dBFS, attack 5 ms, release 80 ms, look-ahead, no auto-level); H.264 High, yuv420p, CRF 18, AAC 160 kb/s, faststart, bitexact flags, metadata stripped.
6. Verify output: h264, aac at $R$, duration within 0.1 s of $T_N$; measure its loudness and true peak (pass 3). Store video and subtitles blobs, then the `Manifest`.

Why not linear `loudnorm`: its linear mode needs measured peak plus gain below the target peak; speech whose true peak exceeds its loudness by more than 14.5 dB (Kokoro at speed 0.85: ≈ 20 dB) forces the dynamic mode, which pumps. A fixed gain and a look-ahead limiter that only touches transients keep $I$ within 1 LU of the target and the true peak below $-1.5$ dBTP after AAC (§2.8 test, three scenes: $-16.4$ LUFS, $-2.0$ dBTP; sine with sparse impulses: $-16.6$ LUFS, $-2.5$ dBTP). One gain serves the whole film, so scenes differ only by their own loudness (Kokoro: 0.65 LU spread over 11 scenes).

11.3 Subtitles. Caption tokens (§10.6; the words when a narration has none) are grouped greedily into cues, closed at a token ending in `. ? ! ; :`, before exceeding 84 characters, or before spanning 6 s; cues longer than 42 characters wrap once at the space nearest the middle; text is HTML-escaped. A cue never splits a formula. The global VTT is built here, since only assembly knows $T_i$.

11.4 Manifest. `artifacts` = {`storyboard`, `render/<id>`, `narration/<id>`}; `versions` = {`assemble`, `ffmpeg`}; `timings_s.assemble`; `metrics` = {`duration_s` $=T_N$, `loudness_in_lufs`, `true_peak_in_dbtp` (narration, pass 1), `loudness_out_lufs`, `true_peak_out_dbtp` (encoded output, pass 3)}. `usage` is zero; the orchestrator adds stage usage.

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
| $Q_7$ `q7_pedagogy` | mean of the 4 rubric scores (1–5) of the judge on storyboard, source equations, 8 keyframes (768 px; for $t_j = (j+\frac12)T/8$ the frame in $[t_j - 1, t_j + 1]$ s of least mean change from its predecessor, nearest $t_j$ among ties) | `--judge` |
| $N_1$ `n1_traced` | fraction of on-screen formulas traced (Algorithm 12.3) | automatic |

`metrics.failures` lists metrics missing their target (`TARGETS`).

**Algorithm 12.3 (equivalence, N1, I2).** Normalization: drop spacing and sizing commands (`\,`, `\quad`, `\left`, `\big`, …) and `&`, tokenize into control words, control symbols and characters, unwrap braces around a single token, strip trailing `.,;`; compare token sequences. Equivalence: parse by SymPy `parse_latex` (Lark backend, font commands removed); an ambiguous parse yields all readings; equalities $a = b$, $c = d$ agree iff $(a-b) \mp (c-d)$ simplifies to 0, expressions iff $a - b$ does. Verdict: True if some pair agrees, False if none, None if either side does not parse. Formulas shown are `math`, `equation` latex and `derive` steps (match markers `{{…}}` removed pairwise). References are the equations and the inline math of $\mathcal D$, each with its parts split at `,`, `;`, `\\` outside brackets. A formula is traced iff it matches a reference (normalized or equivalent), or, as a derive step, is equivalent to its predecessor.

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
| Narration, Kokoro `af_heart`, 789 words (340 s of audio), 4 threads | 186 s |
| `h2.rss`, $n = 4096$, `tol` 1e-5 | factorisation 3.2 s; with the dense reference 8 s |
| `hierarchy`, full instance, 13 steps, 1080p30 | 85 s for 20.5 s of video (71 s before verbs, same machine); about 850 items per state, all redrawn while a step plays |
| `hierarchy`, full instance, 28 word-timed actions, 240p15 draft with the pacing renderer | 73 s for 48 s of video; 0.12 s per redrawn frame |

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
| D8 | 2026-10-07 | `h2.rss` is textbook strong RS-S: $\eta = 2.5$, tree-order greedy distance-2 colouring, fill kept and recompressed with the far field | reference method; variants are computed by consumers from the DataSet |
| D9 | 2026-10-07 | Self-term of (8.7) is the exact cell integral | bounded, mesh-consistent diagonal |
| D10 | 2026-10-07 | GEMMs in `h2` through SciPy's BLAS | NumPy and SciPy OpenBLAS pools contend (about 8×) |
| D11 | 2026-10-07 | `hierarchy` morphs keyed items with per-item `Transform`s | `Scene.add` dissolves groups not yet in the scene |
| D12 | 2026-10-07 | User-supplied arrays enter as `data.npz` by path and SHA-256 | external runs feed primitives without new kernels; the hash pins cache and content |
| D13 | 2026-10-07 | `hierarchy` advances a live state when a step or action plays, not a plan made at build | word-timed actions fire in play order, and continued views replay them at build |
