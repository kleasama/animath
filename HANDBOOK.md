# Animath — Handbook

Developer reference. Notation: $\mathcal{S}$ source, $\mathcal{D}$ document IR, $\mathcal{K}$ knowledge graph, $\mathcal{B}$ storyboard, $\mathcal{V}$ video.

## 1 Specification

1.1 Scope. Animath is the map
$$\Phi : (\mathcal{S}, \pi) \mapsto \mathcal{V} = \Phi_7 \circ \Phi_5 \circ (\Phi_4 \parallel \Phi_6) \circ \Phi_3 \circ \Phi_2 \circ \Phi_1, \tag{1.1}$$
with $\mathcal{S}$ a Markdown, LaTeX (single or multi-file) or PDF source, $\pi$ the parameters, $\mathcal{V}$ an MP4 of duration $T \le 1800$ s.

Parameters $\pi$ (`core.schemas.Params`): duration $T$ (default 180 s), `wpm` (135), audience (undergraduate, graduate, expert), focus, language (en), voice, resolution (1920×1080, 60 fps), style, seed, $N_{\text{retry}}$, budget, approval gates (on). Output: `video.mp4` (H.264, AAC, faststart), `subs.vtt`, `manifest.json` (provenance, digests, timings, usage, metrics). Out of scope: interactive output, streaming, handwriting OCR, non-English narration, multi-hour lectures, GPU-only tools.

1.2 Functional requirements.

| ID | Requirement |
|---|---|
| F1 | Ingest MD, LaTeX, PDF into one IR $\mathcal{D}$: sections, equations, theorems, proofs, algorithms, figures, citations. |
| F2 | Expand macros; resolve `\input`/`\include`, labels, references. |
| F3 | Extract $\mathcal{K}$: concepts, symbols with meaning, equations, dependencies, key results. |
| F4 | Select a teachable subgraph fitting $T$ and audience. |
| F5 | Produce $\mathcal{B}$: scenes with goal, narration, visuals, on-screen math, duration. |
| F6 | Compile scenes from a vetted primitive library; generated code only as fallback. |
| F7 | Compute demonstration data in `numerics`, cached by content hash. |
| F8 | Render headless; check, repair or regenerate failing scenes, at most $N_{\text{retry}}$ times. |
| F9 | Synthesize narration; align it with animation at word granularity; emit subtitles. |
| F10 | Assemble clips, audio, subtitles into $\mathcal{V}$; normalize loudness. |
| F11 | Run every stage on its persisted input (resume, re-run, override). |
| F12 | Optional approval gates after $\mathcal{K}$ and $\mathcal{B}$; edits are respected downstream. |
| F13 | CLI `run`, `stage`, `inspect`, `schema`, `config`, `eval`; Python API mirroring it. |

1.3 Non-functional requirements.

| ID | Requirement | Metric |
|---|---|---|
| N1 | Mathematical correctness | no transcription errors on the golden set; every on-screen formula traced to $\mathcal{D}$ |
| N2 | Determinism | fixed image, seed, threads and cache give identical clips; LLM outputs pinned by the replay cache |
| N3 | Performance | parallel scenes over $p$ processes; target ≤ 30 min end to end for $T = 180$ s on 4 cores |
| N4 | Reliability | typed errors per stage; no silent fallbacks; bounded, logged retries |
| N5 | Concurrency safety | stages pure in their inputs; no shared mutable state; atomic writes |
| N6 | Modularity | each stage behind a protocol; LLM, TTS, renderer, parser swappable |
| N7 | Testability | ≥ 95 % line and branch coverage; golden-set regression; no network in unit tests |
| N8 | Reproducible environment | exact pins (`requirements.lock`); container image |
| N9 | Cost control | token usage in the manifest; budget cap in $\pi$ |
| N10 | Licensing | linked dependencies permissive (`make licenses`); GPL tools (pandoc, x264) only as subprocesses |
| N11 | CPU only | no stage needs a GPU |

1.4 Quality metrics (`eval.metrics.TARGETS`).

| Metric | Key | Definition | Target |
|---|---|---|---|
| $Q_1$ render success | `q1_render` | fraction of renders with `checks.render` | ≥ 0.95 |
| $Q_2$ formula fidelity | `q2_fidelity` | fraction of reference equations (by label, else position) whose normalized LaTeX matches | 1 |
| $Q_3$ sync error | `q3_sync_ms` | $10^3\max_{s,b}\lvert t^R_{s,b} - t^N_{s,b}\rvert$, render against narration bookmark times | ≤ 150 ms |
| $Q_4$ layout | `q4_layout` | failed `layout`, `critic` checks per scene | 0 |
| $Q_5$ coverage | `q5_coverage` | fraction of key nodes addressed by a scene (§6.3) | ≥ 0.9 |
| $Q_6$ duration | `q6_duration` | $\lvert T_{\text{actual}} - T\rvert / T$ | ≤ 0.1 |
| $Q_7$ pedagogy | `q7_pedagogy` | mean rubric score (accuracy, flow, visual relevance, layout) of the LLM judge (§12.5) | ≥ 4/5 |
| $N_1$ traced | `n1_traced` | fraction of on-screen formulas traced (Algorithm 12.3) | 1 |

$Q_2$ needs `--expected`, $Q_7$ needs `--judge`; the others are automatic.

1.5 Pipeline.

| Stage | Map | Module | Deterministic | LLM |
|---|---|---|---|---|
| $\Phi_1$ Ingest | $\mathcal{S}\to\mathcal{D}$ | `ingest` | yes; PDF transcription cached | PDF only |
| $\Phi_2$ Extract | $\mathcal{D}\to\mathcal{K}$ | `extract` | cached | yes |
| $\Phi_3$ Plan | $(\mathcal{K},\pi)\to\mathcal{B}$ | `plan` | cached | yes |
| $\Phi_4$ Compute | data requests $\to$ `DataSet` | `numerics` | yes | no |
| $\Phi_6$ Narrate | $\mathcal{B}\to$ `Narration` | `narrate` | yes | no |
| $\Phi_5$ Animate | $(\mathcal{B},\text{DataSet},\text{Narration})\to$ `SceneRender` | `scene` | cached | codegen, repair, critic |
| $\Phi_7$ Assemble | renders, narration $\to\mathcal{V}$ | `assemble` | yes | no |

$\Phi_4$ and $\Phi_6$ run concurrently after $\Phi_3$. $\Phi_5$ consumes narration timings, so animation follows speech; scenes render in parallel.

1.6 Package layout. Stage modules as above under `src/animath/`; shared `core` (errors, hashing, schemas, store, config, formula matching) and `llm` (protocol, Claude adapter, replay cache, session mode); top level `pipeline.py`, `eval/`, `cli.py`. `tests/` mirrors `src/`; `tests/golden/` holds reference sources and expected IR. `docker/Dockerfile` bundles TeX Live, dvisvgm, ffmpeg, pandoc, cairo/pango, espeak-ng, node and the Kokoro weights.

**Rule 1.1.** A stage module imports only `core`, `llm` and its own subpackage; stages couple through `core.schemas` only.

1.7 Toolchain.

| Concern | Tool | Reason |
|---|---|---|
| MD, LaTeX | pandoc 3.9 JSON AST (`pypandoc-binary`, subprocess); own flattening and macro handling (Algorithm 5.1) | one AST for both paths |
| PDF | arXiv source → LaTeX path; else pypdfium2 rasters → Claude transcription | source beats OCR; CPU only |
| Equation check | `pdflatex` compile; SymPy equivalence (Algorithm 12.3) | catches transcription errors |
| LLM | Claude API: structured outputs, cached system prompt, vision | typed contracts |
| Animation | Manim CE 0.21 (Cairo) | headless, deterministic |
| 3-D | PyVista/VTK offscreen (OSMesa) | headless scientific 3-D |
| TTS | Kokoro-82M ONNX (Apache-2.0); espeak-ng fallback | free, CPU-viable |
| Math speech | Speech Rule Engine 4.1.4 (ClearSpeak) over MathJax 3.2.1, node subprocess | LaTeX → spoken text |
| Alignment | Kokoro token durations | exact to a frame; forced alignment would add torch |

Excluded as GPU-bound, service-bound or redundant: MinerU, Marker, GROBID, Typst, Blender, AV1, WhisperX.

## 2 Environment

2.1 Python ≥ 3.12, `uv`; pins in `requirements.lock` (uv export, no hashes).

2.2 Commands.

| Command | Effect |
|---|---|
| `make setup` | `.venv` from `requirements.lock`, package editable |
| `make lock` | re-resolve pins from `pyproject.toml` |
| `make check` | ruff, ruff format, mypy `--strict`, pytest (coverage ≥ 95 %), licence audit; also CI |
| `animath schema <kind>` | JSON schema of an artifact kind |
| `animath inspect <kind> <digest>` | print a stored artifact |
| `animath config` | effective settings |
| `animath run <src> [-p k=v] [--pages 3-7] [--section 2.1] [--approve \| --edit f]` | $\Phi$; pauses at gates (§12.3) |
| `animath stage <name> <digest> [-p k=v]` | one stage on a stored input (F11) |
| `animath eval <manifest> [--expected doc.json] [--judge]` | metrics of §1.4 |

2.3 Settings (`core.config.Settings`): defaults, then TOML (`--config`), then `ANIMATH_<FIELD>`. Fields: `store`, `model`, `effort`, `max_tokens`, `workers`, `offline`, `llm` (`api` or `session`). The API key is `ANIMATH_API_KEY`, else `ANTHROPIC_API_KEY`; none raises `LLMError`.

## 3 Data contracts and storage

3.1 Artifacts. Frozen Pydantic models (`core.schemas`), serialized as canonical JSON and addressed by SHA-256; binary payloads are blobs referenced by digest.

| Artifact | Producer | Consumer | Key fields |
|---|---|---|---|
| `SourceBundle` | caller | $\Phi_1$ | format, entry, files (path, blob), $\pi$ |
| `DocIR` $\mathcal{D}$ | $\Phi_1$ | $\Phi_2$ | title, blocks (id, type, text, latex, label, level, env, refs, page), macros, bib |
| `KnowledgeGraph` $\mathcal{K}$ | $\Phi_2$ | $\Phi_3$ | nodes (id, kind, name, latex, meaning, key, sources), edges (src, dst, rel) |
| `Storyboard` $\mathcal{B}$ | $\Phi_3$ | $\Phi_4,\Phi_5,\Phi_6$ | title, scenes (id, goal, narration, visuals, math, data, nodes, duration), symbols |
| `DataSet` | $\Phi_4$ | $\Phi_5$ | request (kind, params), arrays (name → blob), meta |
| `Narration` | $\Phi_6$ | $\Phi_5,\Phi_7$ | scene id, audio, duration, words, captions, bookmark times |
| `SceneRender` | $\Phi_5$ | $\Phi_7$ | scene id, clip, duration, bookmark times, checks |
| `Manifest` | $\Phi_7$ | caller | video, subtitles, artifact digests, versions, timings, usage, metrics |

**Invariants 3.1.**
1. Every artifact carries `schema_version`.
2. A stage is skipped iff an artifact is indexed under its key (3.2).
3. Validators enforce unique ids and labels, resolved references, acyclic `depends_on` (Kahn, $O(|V|+|E|)$), visuals cueing existing bookmarks, monotone word and caption times within the duration.

3.2 Hashing. For a JSON value $x$ with canonical encoding $c(x)$ (UTF-8, sorted keys, no whitespace),
$$d(x) = \mathrm{SHA256}(c(x)). \tag{3.1}$$
Blobs are addressed by the SHA-256 of their bytes. Stage $\sigma$ of version $v$ with input digests $d_1,\dots,d_m$ has key
$$k_\sigma = d\big([\sigma, v, d_1, \dots, d_m]\big). \tag{3.2}$$

3.3 Store layout.

| Path | Content |
|---|---|
| `blobs/<d[:2]>/<d[2:]>` | raw bytes |
| `artifacts/<kind>/<d>.json` | canonical artifact JSON |
| `index/<ns>/<key>` | digest under a key; `ns` = artifact kind, `llm`, `gate`, `repair`, `pitfall` |

3.4 Concurrency. Readers see nothing or a complete file. Content-addressed writes are idempotent; index writes are last-writer-wins; reads verify digests.

**Algorithm 3.1 (atomic write).** `mkstemp` in the target directory → write → flush → fsync → `os.replace`; on any exception unlink the temporary and re-raise.

3.5 Pacing fields. `Params.wpm` $\in [80, 220]$ (default 135): speech rate in words per minute, used by the planner (§7.3) and the voice. `Line.pause_s` $\in [0, 30]$ s (default 0): silence after a narration line; a line with a pause ends its utterance.

## 4 LLM access

4.1 `LLM` protocol: `parse(schema, system, prompt, images) -> (instance, Usage)`.

4.2 `Claude`: `beta.messages.stream` with `output_format=schema`, read by `get_final_message` (the SDK refuses non-streaming requests that may exceed 10 min); ephemeral cache on the system prompt; PNG images first; `output_config.effort`; server-side refusal fallback. A `stop_reason` other than `end_turn`, or output failing the schema, raises `LLMError`.

4.3 `Replay`: key $d([t, \text{JSON schema}, \text{system}, \text{prompt}, [d(\text{image}_i)]])$; a hit returns the cached instance with zero usage; an offline miss raises `LLMError`. Unit tests run offline.

4.4 Provenance tag $t$ (`llm.tag`): `session`, else `model:effort`; also `Manifest.versions["model"]`.

4.5 `Session` (`llm = session`): requests answered out of band, by a person or an agent. A miss writes `<store>/pending/<key>/request.json` (schema, system, prompt, images `<i>.png`) and raises `PendingError`; `animath` prints `{"pending": [dirs]}` and exits 0. A rerun validates `<key>/answer.json` against the schema (invalid raises `LLMError`) and caches it through `Replay`. Usage is zero.

## 5 Ingestion

5.1 Interface. `ingest.run(bundle, store, llm, fetch=None, check=None, workers=1) -> (DocIR, Usage)`, with key
$$k_{\text{ingest}} = d\big([\text{ingest}, v, d(\text{bundle}), [\text{fetch}\neq\varnothing], [\text{check}\neq\varnothing]]\big). \tag{5.1}$$
The orchestrator passes `fetch=ingest.fetch_url`, `check=ingest.compile_errors`.

| Module | Content |
|---|---|
| `blocks` | pandoc JSON AST $\to$ `Block`s; `document`, `ir` |
| `latex` | flattening, comments, macros, bibliographies, algorithms, `parse` |
| `pdf` | arXiv lookup, page rasters, transcription, `merge`, `parse` |
| `check` | equation compile check |

5.2 AST map. Display math splits a paragraph. Theorem-like, proof, list and figure blocks carry their prose as `text`, display math inline as `$$…$$`; each display also becomes an `equation` block after the container.

| Pandoc node | Block |
|---|---|
| `Header` | heading, level $\min(\max(\ell,1),6)$, label = explicit id |
| `Para`, `Plain` | paragraph(s) and equation(s) |
| `Math DisplayMath`, raw `equation`/`align`/`gather`/`multline` | equation; `align`$\to$`aligned`; `gather`, `multline`$\to$`gathered` |
| `Div` of a theorem class (§5.3) / `proof` | theorem (`env` = class) / proof |
| other `Div` with id | its blocks; the first unlabelled one takes the id |
| `BulletList`, `OrderedList` | list, one line per item |
| `Figure` | figure, `text` = caption |
| `CodeBlock` | code |
| token `ANIMATHALG<i>` | algorithm $i$ (Algorithm 5.1) |
| other | paragraph of all inline text; rules and non-math raw blocks dropped |

5.3 Theorem classes: `blocks.THEOREMS` $\cup$ `\newtheorem` names. Heads (`Theorem 1`, `Proof.`) are stripped; an optional name stays as `(Name).`.

5.4 Labels. An equation takes its first `\label`; later labels of the same display are aliases rewritten in `refs`. `\label`, `\nonumber`, `\notag` are removed from `latex`. Inline: `\eqref{l}` $\to$ `(l)`, `\ref{l}` $\to$ `l`, citations $\to$ `[k₁; k₂]`. Unresolved references raise `IngestError` (MD, LaTeX).

**Algorithm 5.1 (LaTeX).**
1. Decode UTF-8, else Latin-1; strip comments (`%` not after an odd run of `\`).
2. Resolve `\input`/`\include` recursively from the entry directory; cycles and missing files raise.
3. Macros: `\(re|provide|new)command`, `\DeclareMathOperator`, `\def` $\mapsto$ declaration (`DocIR.macros`).
4. Bibliography: `thebibliography`; else `<entry>.bbl`; else `.bib` files of `\bibliography`/`\addbibresource`.
5. Expand `\newcolumntype` letters in column specs; replace `algorithm`/`algorithmic` environments by tokens with text = caption, then one step per line, indented by nesting.
6. Pandoc `latex-auto_identifiers`; map by §5.2.

**Algorithm 5.2 (PDF).**
1. If `fetch` is given and page 1 carries an arXiv id, fetch `arxiv.org/e-print/<id>`; a TeX source (main file: `\documentclass` and `\begin{document}`, shallowest path) goes to Algorithm 5.1. Failure is logged, then step 2.
2. Render pages at 144 dpi to PNG.
3. Transcribe chunks of 4 pages in parallel (`workers`) into `pdf.Transcript` (system prompt `pdf.SYSTEM`).
4. If `check` is given, equations failing Algorithm 5.3 return to the model with their errors; at most $N_{\text{retry}}$ repairs, then `IngestError`.
5. Merge: first non-null title; duplicate labels dropped after the first; equations without LaTeX become paragraphs; levels kept for headings only; refs filtered to known labels and bib keys.

**Algorithm 5.3 (equation check).** Unbalanced braces fail without TeX. The rest are typeset in one `pdflatex -draftmode` run (amsmath, amssymb, bm, document macros), each after `\typeout{@@animath-eq-i}`; the first `! ` line after marker $i$ is the error of equation $i$; an error before any marker is a preamble error and raises.

5.5 Golden set (`tests/golden/`): sources, PDF transcript fixture, expected IR. Regenerate with `ANIMATH_UPDATE_GOLDEN=1 .venv/bin/pytest tests/ingest/test_golden.py` and review the diff.

| Case | Format | Exercises |
|---|---|---|
| `efie` | MD + `.bib` | YAML title, labelled `$$`, raw `\eqref`, citations, theorem div, list |
| `gmres` | LaTeX, `\input`, `.bib` | macros, `align` aliases, algorithm, named theorem, proof, lemma |
| `gauss` | PDF + transcript | rasters, replay, merge, theorem with display |

5.6 Decisions.

| # | Decision | Reason |
|---|---|---|
| I1 | pandoc pinned through `pypandoc-binary` | identical AST everywhere (N2) |
| I2 | Ingest checks by TeX compilation; SymPy equivalence in planning and evaluation | syntax errors caught at $O(1)$ TeX runs per chunk |
| I3 | PDF output normalized (Algorithm 5.2, step 5), not rejected | model output is a hint; MD and LaTeX stay strict |
| I4 | Figure image paths dropped | captions suffice for $\Phi_2$ |

## 6 Knowledge extraction

6.1 Interface. `extract.run(doc, store, llm, retries=3) -> (KnowledgeGraph, Usage)`, with key
$$k_{\text{extract}} = d\big([\text{extract}, v, d(\mathcal{D})]\big). \tag{6.1}$$

| Module | Content |
|---|---|
| `draft` | output schema `Draft` (`DNode`, `DEdge`), `SYSTEM`, block lines, `chunks`, `prompt` |
| `graph` | node validation (`node`), merge of a draft into the graph (`merge`) |

6.2 Semantics. Node kinds: concept, symbol (with `latex`, `meaning`), equation (one display), result, algorithm. Edges: $a \xrightarrow{\text{depends\_on}} b$ iff $a$ cannot be understood before $b$; $a \xrightarrow{\text{defines}} b$ iff $a$ introduces $b$; $a \xrightarrow{\text{uses}} b$ otherwise. `Node.sources` are block ids.

6.3 Key nodes. `key` marks the set $\mathcal{K}^\ast$ a video must cover:
$$Q_5 = \frac{|\{n\in\mathcal{K}^\ast : n \in \textstyle\bigcup_s \text{nodes}(s)\}|}{|\mathcal{K}^\ast|}. \tag{6.2}$$

**Algorithm 6.1 (extraction).**
1. Split $\mathcal{D}$ into sections; pack them greedily into chunks of at most $4\cdot 10^4$ characters of block lines `[id type env label] latex|text`; a longer section is packed block by block.
2. For each chunk in order: prompt = title, macros, known nodes (`id (kind): name`), block lines; `llm.parse(Draft, SYSTEM, prompt)`.
3. Merge (Algorithm 6.2). On problems, re-prompt with the draft and the problem list; at most $N_{\text{retry}}$ repairs, then `ExtractError`.
4. Store under (6.1).

**Algorithm 6.2 (merge).** A draft node is rejected unless its id matches `[a-z0-9][a-z0-9_-]*`, all sources are block ids, an equation has an equation source, and a symbol has `latex` and `meaning`. An equation's `latex` is replaced by that of its first equation source. A known id of the same kind unites sources and `key`; another kind is a problem. Edges join known nodes, no self-loops; duplicates are dropped. At the end at least one node is key, and `KnowledgeGraph` validation errors are problems.

6.4 Golden drafts (`tests/extract/golden/<case>.json`) are hand-written `Draft`s for the IR of §5.5, replayed through `Replay`; tests check key nodes, sources, equation fidelity and offline reruns.

6.5 Decisions.

| # | Decision | Reason |
|---|---|---|
| X1 | Equation `latex` copied from $\mathcal{D}$, never from the model | $Q_2$ and N1 by construction |
| X2 | Invalid drafts repaired by the model, not normalized | the graph gates planning (F12); silent drops hide errors (N4) |
| X3 | Chunks sequential with a ledger of known nodes | cross-chunk ids and edges |
| X4 | Key excludes $\pi$ | audience and focus act in $\Phi_3$ |

## 7 Storyboard

7.1 Interface. `plan.run(graph, params, catalog, store, llm, kernels=None, speaker=None) -> (Storyboard, Usage)`. `catalog` maps primitive names to argument JSON schemas (`scene.catalog()`); `kernels` maps data kinds to parameter schemas; `speaker` (`id`, `lines`: the narration's `Verbalizer`) gives the spoken form of lines. The orchestrator passes all three (Rule 1.1). With $\pi_3$ = (`duration_s`, `wpm`, `audience`, `focus`, `language`, `max_retries`),
$$k_{\text{plan}} = d\big([\texttt{plan}, v, d(\mathcal{K}), d([\pi_3, \text{catalog}, \text{kernels}, \text{speaker.id}])]\big). \tag{7.1}$$

| Module | Content |
|---|---|
| `select` | seeds, closure, budget, order (Algorithm 7.1) |
| `draft` | output schema `Draft`, system and task prompts |
| `check` | script (Algorithm 7.2), validation and conversion to `Storyboard` (Algorithm 7.3) |

**Algorithm 7.1 (selection, F4).**
1. Seeds $S$: nodes whose id or a source block equals `focus`, or whose name contains it (case-folded); no match raises `PlanError`. Without focus: key nodes, else nodes no `depends_on` edge points to.
2. Breadth-first closure along out-edges with hop $h(v)$, to depth $\delta$ = ∞, 2, 1 for undergraduate, graduate, expert.
3. Budget $N = \max(|S|, \lceil T/15 \rceil)$: keep the $N$ nodes least in $(h, \text{graph order})$; seeds and parents of kept nodes survive.
4. Order by Kahn on `depends_on` (prerequisites first), ties by graph order.
5. Context: the other nodes with `latex`, whose formulas scenes may show.

7.2 Draft. The model returns `Draft`: scenes with `narration`, optional `loop` and `after` lines, visuals (`args` a JSON string), data requests (`params` a JSON string), node ids, symbols. A line carries `text`, `bookmark`, `pause` and `actions` $(\texttt{visual}, \texttt{do}, \texttt{parts}, \texttt{word}, \texttt{color})$; a loop carries items `over`, first-pass `lines`, `brief` lines and speed-up $s$ (default 2). JSON strings keep the schema closed for structured outputs. The prompt carries audience, $T$, `wpm`, scene target $\max(1, \operatorname{round}(T/40))$, word target $\operatorname{round}(0.85\,\rho T)$ with $\rho$ = `wpm`/60, seeds, selected nodes and edges, context formulas, catalog, kernels.

7.3 Pacing. Line $\ell$ of $n_\ell$ spoken words lasts $s_\ell = n_\ell/\rho$; $n_\ell$ counts the words of `speaker.lines` (one call per draft), else a weighted token estimate (TeX control word or alphanumeric run; inline math weighs 1.5). The slot of $\ell$ is
$$\sigma_\ell = s_\ell + p_\ell + g\,[\ell \text{ ends an utterance and is not last}], \qquad g = 0.35\ \text{s}, \tag{7.2}$$
with pause $p_\ell$; a line ends an utterance if it ends in `.`, `!` or `?` (closing quotes and brackets allowed) or $p_\ell > 0$. A line on which a visual enters, and the last line, hold $p_\ell \ge 1$ s. Scene $i$ is estimated at $E_i = L + \sum_\ell \sigma_\ell$, $L = 0.4$ s, and $E = \sum_i E_i$. A draft is admissible only if
$$\lvert E - T \rvert \le 0.1\,T, \tag{7.3}$$
and scene durations are
$$d_i = T\,E_i / E, \qquad \textstyle\sum_i d_i = T, \tag{7.4}$$
rounded to 1 ms. The narration speaks the same words with the same lead, gaps and pauses, so $E$ is its length (10.5) and (7.3) bounds $Q_6$. Line onsets are $o_\ell = L + \sum_{k<\ell} \sigma_k$; a `word` fires at $o_\ell + s_\ell \phi$, $\phi$ the share of weighted tokens before it, and its action carries `frac` $= \min(0.99,\ s_\ell \phi/\sigma_\ell)$ for renders without word times (§9.6).

**Algorithm 7.2 (script).**
1. Lines of `narration`; the loop's `lines` with `{}` replaced by the first item; one line per `brief` entry; `after`. A line without bookmark gets `#k`, $k$ its index. Each action becomes `Action{at: bookmark, word, do, parts, color}` of its visual.
2. Holds as in §7.3.
3. Passes $q = 1, \dots, |\texttt{over}|-1$ replay the first pass's $n$ actions. With $D_1$ the first pass's slot sum and $\tau_j$ the onset of action $j$ in it,
$$D_q = \max\big(D_1 s^{-q},\; n \cdot 1\ \text{s}\big). \tag{7.5}$$
Brief lines map one to one onto passes, or one brief line carries all passes. A brief line's pause grows until $\sigma_b \ge \sum D_q$; action $j$ of pass $q$ at offset $O_q$ becomes `Action{at: b, frac: (O_q + \tau_j D_q/D_1)/\sigma_b, rate: D_1/D_q}` with `{}` replaced by item $q$.

7.4 Views. A visual whose args name a `view` continues the last visual of that view (same primitive). It takes the old args (without `persist`, `until`, `replaces`, `enter`), `resume: true`, and the old actions (without `indicate`) as initial state (`at: null`), then its own actions, `until` and `replaces`; other differing args are an error. If the old visual is on screen at the end of the previous scene and the new one has no `at`, the new one gets `enter: none` and the old one `persist: true`: a seamless cut. Otherwise the view re-enters with its state.

**Algorithm 7.3 (validation).** Errors are collected, not raised.

| Check | Rule |
|---|---|
| primitive | name in catalog; `args` a JSON object valid against its schema; continued views exempt |
| arrays | every `{"data", "array"}` names an existing request; `part` set outside `matrix` |
| data | `params` a JSON object; kind known and params valid when kernels are given |
| cues | `at` names a bookmark; `until` a later one |
| actions | visual exists; action valid against the primitive's `Action` schema; `word` a plain word of the line outside math; line within the visual's lifetime |
| morphs | `replaces` names an earlier visual whose `until` equals this `at` |
| regions | overlapping lifetimes need disjoint regions (`main` meets `left`, `right`) |
| motion | estimated changes at most 7 s apart over $[0, E_i]$ |
| loop | ≥ 2 items and ≥ 1 line; $s \ge 1$; one brief line per later item, or one without `{}` |
| lines | bookmarks do not start with `#`; pauses in $[0, 30]$ s |
| views | `view`, `until` strings; a continued view keeps its args |
| formulas | `math`, `equation` and `derive` steps traced (Algorithm 12.3) to selected and context node latex |
| scene | ≥ 1 visual; nodes within the selection |
| board | (7.3); seed coverage ≥ 0.9; unique scene ids |

7.5 Symbol ledger. `Storyboard.symbols` = draft symbols, overridden by selected symbol nodes (`latex` $\mapsto$ `meaning`, else `name`).

**Algorithm 7.4 (plan).** Key hit $\Rightarrow$ return. Else select; for at most $N_{\text{retry}}+1$ attempts: parse `Draft`, validate; on success store and return; else append the draft and its errors to the prompt. Exhaustion raises `PlanError`. Usage is summed.

7.6 Decisions.

| # | Decision | Reason |
|---|---|---|
| P1 | Selection deterministic; LLM only for scenes and prose | reproducible F4, smaller prompt |
| P2 | Durations from estimated speech (7.4), not from the model | $\sum d_i = T$ exactly |
| P3 | `part` required on non-matrix array refs | real or complex is unknown before $\Phi_4$ |
| P4 | Region conflicts checked at plan time | saves renders and repairs |
| P5 | `jsonschema` validates against the catalog | no import of `scene` |
| P6 | 135 wpm, 0.35 s gaps, 1 s holds | lecture pace |
| P7 | Actions written on lines, expanded into `Args.actions` | motion where it is spoken; renders need no plan knowledge |
| P8 | Loop passes computed, not written | exact speed-up and readable floor (7.5) |
| P9 | Motion check at 7 s on estimates, 8 s on renders (§9.12) | static stretches caught before rendering |
| P10 | A view continues its last visual even after a gap | a view yields to a zoom and returns unchanged |
| P11 | Word actions carry their estimated slot fraction | they fire near their word without word times |
| P12 | Spoken words from the narration's verbalizer | weighted tokens misjudge formulas: $\int_{-1}^{1} f(x)\,dx$ is 12 spoken words, weight 9 |
| P13 | On-screen formulas traced at plan time | admissible boards have $N_1 = 1$; worked values go to data requests |
| P14 | Formulas of the whole graph may be shown | node latex comes from $\mathcal{D}$, so $N_1 = 1$ still holds |

## 8 Numerics

8.1 Interface. `numerics.compute(request, store) -> DataSet`. `request.kind` selects a `Kernel`: frozen bounded parameters, pure `run() -> (arrays, meta)`. Invalid kinds or parameters, `LinAlgError` and non-finite arrays raise `ComputeError`. `numerics.load(ds, store)` returns the arrays. With $p$ the validated parameters,
$$k = d\big([\texttt{numerics}, v, \text{kind}, d(p)]\big). \tag{8.1}$$
Each array is one `.npy` blob (`allow_pickle=False`); `meta.version` $= v$.

8.2 Kinds.

| Kind | Parameters | Arrays | Meta |
|---|---|---|---|
| `quadrature.rule` | `n`, `a`, `b` | `nodes`, `weights` | `degree` |
| `quadrature.convergence` | `integrand` ∈ {exp, runge, osc, abs}, `a`, `b`, `n_max` | `n`, `gauss`, `trapezoid`, `simpson` | `exact` |
| `mom.efie_cylinder` | `ka`, `n` ($n \ge 10\,ka$) | `phi`, `current`, `exact` | `rel_error` |
| `bem.dlp_ellipse` | `a`, `b`, `n_max` | `n`, `error`, `t`, `density` | `target` |
| `krylov.gmres` | `operator`, `tol`, `maxiter` $\le 256$, `ritz` | `x`, `residual`, `eigs`, `ritz`, `ritz_k` | `iterations`, `converged`, `true_residual` |
| `krylov.cg` | `operator`, `tol`, `maxiter` | `x`, `residual`, `error_a`, `bound` | `kappa`, `iterations`, `converged` |
| `h2.rss` | `geometry` ∈ {plate, sphere}, `n`, `leaf`, `eta`, `kappa`, `tol`, `precision`, `seed` | `points`, `perm`, `box`, `range`, `near`, `far`, `dof` (CSR, `_ptr`), `stage`, `stage_norm`, `dag`, `schur`, `schur_norm`, `fill`, `fill_norm`, `active`, `top` | `depth`, `top_level`, `top_size`, `colours`, `stages`, `error` |
| `data.npz` | `path` (absolute), `sha256` | numeric members | 0-d `meta` member, a JSON object |

Operators (discriminator `name`): `poisson1d` $\operatorname{tridiag}(-1,2,-1)$; `convdiff` $\operatorname{tridiag}(-1-P,2,-1+P)$, $P$ the cell Péclet number; `efie` (§8.4); `dlp` (§8.5). Right-hand sides: $\mathbf{1}$, $\mathbf{1}$, $\mathbf{V}$, $g$.

8.3 Quadrature. Gauss–Legendre nodes $x_i$ are the eigenvalues of the Jacobi matrix with $J_{k,k+1} = k/\sqrt{4k^2-1}$; weights $w_i = 2 v_{i,1}^2$ (Golub–Welsch). The rule is exact on $\mathbb{P}_{2n-1}$ with remainder
$$\int_a^b f - Q_n f = \frac{(b-a)^{2n+1}(n!)^4}{(2n+1)\,((2n)!)^3}\, f^{(2n)}(\xi). \tag{8.2}$$
Convergence data use $n = 3,5,\dots$ for all rules, so composite Simpson is defined.

8.4 MoM: TM EFIE on a PEC cylinder of radius $a$, $\lambda = 1$, $E^i_z = e^{-jkx}$, convention $e^{j\omega t}$:
$$E^i_z(\boldsymbol\rho) = \frac{k\eta}{4}\int_C J_z(\boldsymbol\rho')\,H_0^{(2)}(k|\boldsymbol\rho-\boldsymbol\rho'|)\,dl'. \tag{8.3}$$
Pulse basis, point matching at $n$ equispaced points, $w = 2\pi a/n$:
$$Z_{mn} = \frac{k\eta w}{4}H_0^{(2)}(kR_{mn}),\quad Z_{mm} = \frac{k\eta w}{4}\Big[1 - \frac{2j}{\pi}\ln\frac{\gamma k w}{4e}\Big],\ \gamma = e^{\gamma_E}. \tag{8.4}$$
Reference: $J_z(\phi) = \frac{2}{\pi\eta\, ka}\sum_{m} j^{-m} e^{jm\phi}/H_m^{(2)}(ka)$, $|m| \le ka + 4(ka)^{1/3} + 10$. Error $O(1/n)$.

8.5 BEM: interior Dirichlet problem by the double-layer potential, $\Phi(x,y) = -\frac{1}{2\pi}\ln|x-y|$:
$$-\tfrac12\mu(x) + \int_\Gamma \frac{\partial \Phi(x,y)}{\partial\nu_y}\mu(y)\,ds_y = g(x),\qquad \lim_{y\to x}\frac{\partial\Phi}{\partial\nu_y} = -\frac{\kappa(x)}{4\pi}. \tag{8.5}$$
Nyström with the trapezoid rule on $y(t) = (a\cos t, b\sin t)$; data $u = e^{x_1}\cos x_2$ at $(a/4, b/4)$. Exponential convergence. Check: $A\mathbf 1 = -\mathbf 1$ (Gauss lemma).

**Algorithm 8.1 (GMRES with trace).** $x_0 = 0$, $\beta = \|b\|$, $v_1 = b/\beta$. For $k = 1,\dots,m$: modified Gram–Schmidt Arnoldi step gives column $k$ of $\bar H_k$; record Ritz values $\sigma(H_k)$; apply previous Givens rotations, form $G_k$ annihilating $h_{k+1,k}$, update $g$; $\|r_k\|/\beta = |g_{k+1}|/\beta$. Stop at `tol` or $h_{k+1,k} \le 10^{-14}\|Av_k\|$ (happy breakdown). Then $x_k = V_k R_k^{-1} g_{1:k}$. Ritz values cost $O(m^4)$, hence `maxiter` $\le 256$.

**Algorithm 8.2 (CG with trace).** Requires $A = A^H \succ 0$ (symmetry test, Cholesky). Records $\|r_k\|/\|b\|$ and $\|e_k\|_A/\|e_0\|_A$, bounded by
$$\frac{\|e_k\|_A}{\|e_0\|_A} \le 2\Big(\frac{\sqrt\kappa-1}{\sqrt\kappa+1}\Big)^k. \tag{8.6}$$

8.6 Implementation notes. Dense NumPy/SciPy, vectorized assembly. Kernels are deterministic and side-effect free, so concurrent `compute` calls are safe (§3.4). Matrix symbols keep textbook case; `N803`/`N806` are silenced per file.

8.7 Strong recursive skeletonisation (`h2.rss`). Points: plate, the $m \times m$ cell centres of the unit square ($n = m^2$, $w = 1/n$); sphere, the Fibonacci lattice on the sphere of radius $\tfrac12$ centred in the unit cube ($w = \pi/n$). With $G(r) = e^{i\kappa r}/(4\pi r)$ and $\square_i$ the square of side $\sqrt w$ centred at $x_i$,
$$A_{ij} = w\,G(|x_i - x_j|)\ (i \ne j),\qquad A_{ii} = \int_{\square_i} G(|y|)\,dy = \frac14\sum_{q=1}^{16} c_q\,\frac{e^{i\kappa\rho_q} - 1}{i\kappa},\quad \rho_q = \frac{\sqrt w}{2\cos\theta_q}, \tag{8.7}$$
$\theta_q = \tfrac\pi8(u_q + 1)$, $(u_q, c_q)$ the 16-point Gauss–Legendre rule; $\kappa = 0$ gives $A_{ii} = \sqrt w\,\ln(1+\sqrt2)/\pi$. The factorisation runs in `precision` (complex64 by default, real if $\kappa = 0$), `tol` $\ge 10\epsilon$.

Cluster tree: balanced binary of depth $d = \min\{d : \ell\,2^d \ge n\}$, $\ell$ = `leaf`, breadth-first numbering with children $2t+1, 2t+2$; each split at the rank median along the axis minimising the larger child diameter; $[l_t, h_t]$ the tight bounding box, $\operatorname{diam} t = |h_t - l_t|$. Lists, level by level from $N(0) = \{0\}$, with $C(t) = \operatorname{ch} N(\operatorname{pa} t)$ and $\delta$ the box distance:
$$F(t) = \{s \in C(t) : \delta(t,s) > 0,\ \tfrac12(\operatorname{diam} t + \operatorname{diam} s) \le \eta\,\delta(t,s)\},\qquad N(t) = C(t) \setminus F(t). \tag{8.8}$$
Every leaf pair lies in exactly one block $t \times s$, $s \in N(t)$ at level $d$ or $s \in F(t)$ at some level. Each level is coloured greedily in tree order,
$$c(t) = \min\{c \ge 0 : c \ne c(u)\ \forall u \in N^2(t),\ u < t\},\qquad N^2(t) = \textstyle\bigcup_{s \in N(t)} N(s), \tag{8.9}$$
so stages of one colour touch disjoint neighbourhoods and may run in parallel. Stage order is (colour, tree index); the DAG links each stage to every later stage in $N^2(t)$.

Column ID by pivoted QR $M P = Q\begin{bmatrix} R_{11} & R_{12} \\ 0 & R_{22}\end{bmatrix}$, $S$ the first $k$ pivots, $R$ the rest, $\varepsilon$ = `tol`:
$$k = \#\{j : |r_{jj}| > \varepsilon\,|r_{11}|\},\qquad T = R_{11}^{-1}R_{12},\qquad \|M_{:,R} - M_{:,S}T\|_F = \|R_{22}\|_F. \tag{8.10}$$

**Algorithm 8.3 (strong RS-S).** Active DOFs $B_t$ (leaf indices at level $d$), near blocks $D_{ts} = A_{B_t B_s}$, fill $\Phi = 0$. Top level $\tau = \lambda_F - 1$, $\lambda_F$ the coarsest level with a far pair ($\tau = d$ if none). For $\lambda = d, \dots, \tau + 1$ and $t$ in stage order:
1. Far field $K_{BF} = [A_{B_t B_s} + \Phi_{ts}]_{s \notin N(t)}$, $K_{FB}$ likewise; ID (8.10) of $\begin{bmatrix} \mathrm R(K_{FB}) \\ \mathrm R(K_{BF}^{T}) \end{bmatrix}$, $\mathrm R(\cdot)$ the thin-QR triangle.
2. Shear rows $X_R \leftarrow X_R - T^{T}X_S$, and columns likewise, in $D_{tt}$, $D_{ts}$, $D_{st}$: far couplings of $R$ vanish up to (8.10).
3. LU of $\tilde A_{RR}$; with $J = S \cup \bigcup_{s \in N(t)\setminus t} B_s$, $L_{21} = \tilde A_{JR}\tilde A_{RR}^{-1}$, $U_{12} = \tilde A_{RR}^{-1}\tilde A_{RJ}$.
4. Schur update
$$\tilde A_{JJ} \leftarrow \tilde A_{JJ} - L_{21}\tilde A_{RJ}; \tag{8.11}$$
block $(a, b) \in N(t)^2$ adds to $D_{ab}$ if $b \in N(a)$, else to $\Phi_{ab}$. Then $B_t \leftarrow B_t(S)$.

After each level $B_p = B_{2p+1} \cup B_{2p+2}$; $D_{pq}$, $q \in N(p)$, is assembled from child near blocks and, for far child pairs, $A$ plus their fill; remaining fill moves to the parents. Finally dense LU of $[D_{pq}]$ on level $\tau$. Solve: forward sweep (shear, $L_{21}$, $\tilde A_{RR}^{-1}$), top solve, backward sweep ($U_{12}$, $T$). Reported error: $\|\tilde x - x\|/\|x\|$, $x = A^{-1}g$ by dense complex128 LU, $g$ complex Gaussian from `seed`. A singular pivot block raises `ComputeError`.

Trace: `stage` rows $(t, \lambda, c(t), n_t, k_t, r_t, |J|)$; `stage_norm` $(\|K_{BF}\|_2, \|K_{FB}\|_2, \|R_{22}\|_F)$; `schur` rows (stage, $a$, $b$, fill) with $\|\Delta\|_F$ in `schur_norm`; `fill` rows $(\lambda, a, b)$ with norms; `active` $(\lambda, \sum_t |B_t|)$ per level and at the top; `dof` per stage $[B_t(S), B_t(R)]$; `top` the top DOFs.

Implementation: GEMMs through SciPy's BLAS (`get_blas_funcs`), since NumPy and SciPy bundle separate OpenBLAS builds whose thread pools contend (D5); 2-norms of tall blocks from their thin-QR triangles; reference matrix assembled in 512-row slabs.

8.8 File-backed data (`data.npz`). The archive is read once and must match `sha256`, so key (8.1) pins the content and later runs need no file. Members load with `allow_pickle=False`; a mismatch, unreadable archive, non-numeric member or non-object `meta` raises `ComputeError`. The kind brings externally computed arrays into scenes; its schema tells the planner not to invent it.

## 9 Scenes and rendering

**Algorithm 9.1 (scene generation, $\Phi_5$).** For each scene $s\in\mathcal{B}$, in parallel:
1. Layout: bounding boxes on the semantic grid; reject overlap or off-frame placement (§9.5).
2. Compile $s$ from the primitive library; a visual outside it is generated by the LLM (`code`, §9.10).
3. Static gate of generated code.
4. Draft render; on error, localized repair (§9.11), at most $N_{\text{retry}}$ times.
5. Critic: motion and content checks, then VLM on keyframes (§9.12); failures go to pitfall memory.
6. Final render at target quality.

9.1 Modules. `scene.layout` (geometry, no Manim); `scene.primitives` (registry `PRIMITIVES`; `catalog()` of argument schemas, described by the primitives' docstrings); `scene.render` (`timeline`, `compose`, `schedule`, `shoot`, `render`).

9.2 Primitives. A `Visual` names a primitive and its arguments; every argument model extends `Args`:

| Field | Meaning |
|---|---|
| `region` | grid cell (§9.3), default `main` |
| `until` | bookmark that removes the visual |
| `enter` | `auto` (write or fade in), `fade`, `none` |
| `replaces` | index of an earlier visual whose `until` is this `at`; this one morphs out of it |
| `view`, `persist` | persistent view (§7.4); `persist` suppresses the exit at scene end |
| `actions` | timed changes of parts (§9.6) |

Numerical arguments are literals or `ArrayRef` $(i, a)$: array $a$ of the `DataSet` answering `scene.data[i]`. Complex arrays select `part` $\in$ {`abs`, `real`, `imag`} wherever a real array is drawn; `matrix` takes complex input directly.

| Primitive | Arguments | Visual | Parts | Own verbs |
|---|---|---|---|---|
| `text` | `text` (LaTeX text mode) | `Tex` | TeX substrings | |
| `equation` | `latex` | `MathTex` | TeX substrings | |
| `derive` | `steps` ($\ge 2$; `{{...}}` marks matched parts) | `MathTex` chain, `TransformMatchingTex` at $t_e + k(t_x-t_e)/n$ unless `next` advances it | index paths | `next` |
| `matrix` | `entries` (strings or `ArrayRef`) | entries if $\max(m,n) \le 8$, else heatmap of $\log_{10}\lvert a_{ij}\rvert$ | `row:i`, `col:j`, `entry:i:j` (1-based), `brackets` | |
| `plot` | `series` ($\le 5$; `x`, `y`, `label`), `xlabel`, `ylabel`, `logy` | `Axes`, graphs, legend | `axes`, `labels`, `series:k`, `legend` | |
| `field` | `values` $u_{ij}$ at $(x_j, y_i)$ | viridis heatmap | | |
| `surface` | `points` $(n,3)$, `faces` $(m,3)$, `scalars`, `azimuth`, `elevation` | PyVista offscreen image | | |
| `trace` | `lines` (plain text), `steps` (line indices) | monospace listing with cursor, uniform visits unless `goto` moves it | `line:k` (0-based), `cursor` | `goto` |
| `hierarchy` | `data`, `level`, `done`, `coloured`, `views` ⊆ {`plate`, `operator`}, `steps` | cluster boxes, block operator (§9.15) | `t`, `s`, `cluster:k`, `colour:c`, `block:a:b` | board verbs (§9.15) |
| `code` | `code` (§9.10) | generated | index paths | the snippet's `act` |

Every primitive accepts dotted index paths (`1.0`) as parts. A TeX part isolates every occurrence of the substring that cuts no control word or symbol (`t` is not isolated in `\to`). Undelimited arguments of `^`, `_`, accents and font macros are braced first (`x^2` → `x^{2}`), since an isolation marker before them breaks TeX. Blank lines in `equation` and `derive` latex are collapsed.

9.3 Semantic grid. For frame $F = [-W/2, W/2] \times [-H/2, H/2]$, $H = 8$, $W = 8w/h$, a region with normalized box $(u_0, v_0, u_1, v_1)$ occupies
$$C = [-W/2 + u_0 W,\; -W/2 + u_1 W] \times [-H/2 + v_0 H,\; -H/2 + v_1 H]. \tag{9.1}$$

| Region | $(u_0, v_0, u_1, v_1)$ |
|---|---|
| `title` | (0.04, 0.86, 0.96, 0.97) |
| `main` | (0.04, 0.14, 0.96, 0.84) |
| `left` | (0.04, 0.14, 0.49, 0.84) |
| `right` | (0.51, 0.14, 0.96, 0.84) |
| `footer` | (0.04, 0.03, 0.96, 0.12) |

`left` and `right` partition `main`; either with `main` at once is a conflict.

9.4 Fit. A mobject of size $w \times h$ in cell $C$ is scaled by
$$s = \min\big(1,\; w_C / w,\; h_C / h\big) \tag{9.2}$$
and centred. Raster primitives are built at cell height.

9.5 Layout check. A placement is $p = (B_p, [t_0, t_1), s_p)$, $B_p$ the measured bounding box. The layout is rejected (`AnimateError`) iff $B_p \not\subseteq F$ or $s_p < 0.4$ for some $p$, or for some $p \ne q$
$$[t_0^p, t_1^p) \cap [t_0^q, t_1^q) \ne \emptyset \;\wedge\; \lvert B_p \cap B_q \rvert > 0. \tag{9.3}$$
Actions change parts in place, so the build box bounds the visual unless an action moves a part out.

9.6 Timeline and cues. With narration, bookmark times $\tau_b$, word onsets and duration $T$ come from `Narration`. Without, line slots follow speech at `wpm`, gaps $g = 0.35$ s and pauses, scaled to `duration_s`; words spread uniformly over their line. A visual lives on $[t_0, t_1)$, $t_0 = \tau_{\texttt{at}}$ (else 0), $t_1 = \tau_{\texttt{until}}$ (else $T$).

| Cue | Start | Run time |
|---|---|---|
| entry | $t_0$ | 1.5 s (`Write` or `FadeIn`); 1.2 s morph when `replaces` (`TransformMatchingTex` between formulas, else `ReplacementTransform`); 0 for `enter: none` |
| action | $\min\big(\max(t_e, t_a),\; t_x - r\big)$, not before $t_e$ | $r = \min\big(\max(0.25,\ 1/\texttt{rate}),\ t_x - t_e\big)$; error if $r < 0.25$ |
| own | spread over $[t_e, t_x)$; error if $t_e \ge t_x$ | `derive` $\min(1,\ 0.8\,s)$, `trace` $\min(0.4,\ 0.8\,s)$ for slot $s$ |
| exit | $t_x = \max(t_0, t_1 - 0.6)$ | 0.6 s `FadeOut`; none if replaced or `persist` without `until` |

$t_e$ is the entry end; $t_a$ the onset of `word` (case and punctuation ignored) in the slot $[\tau_{\texttt{at}}, \tau_{\text{next}})$, else $\tau_{\texttt{at}} + \texttt{frac}\,(\tau_{\text{next}} - \tau_{\texttt{at}})$. An action with `at: null` is initial state, applied at build. A visual with `resume` (continued view, §7.4) applies its initial own animations at build and has no others. Generic verbs: `show` (hidden at build, then written or faded in), `hide`, `dim` (opacity 0.2), `indicate` (`Indicate`, or `Circumscribe` if not vector), `mark` (colour, default yellow), `unmark`. Verbs change mobjects in place.

**Algorithm 9.2 (schedule).** Cues $(t_k, r_k)$, frame rate $f$, $N = \operatorname{round}(Tf)$.
1. $a_k = \operatorname{round}(t_k f)$; drop $a_k \ge N$; $n_k = \min(\operatorname{round}(r_k f), N - a_k)$.
2. In order of $(a_k, k)$, a cue joins the current cluster if $a_k$ lies before its end, else opens one; a cluster ends at $\max_k (a_k + \max(n_k, 1))$.
3. Each cluster is one `play` of `Delayed` cues: set up at frame $a_k$, interpolated over $n_k$ frames, finished at $a_k + n_k$; waits fill gaps.

Overlapping cues keep their run times, every cue starts on its own frame ($Q_3 \le 1/(2f)$), and the clip has exactly $N$ frames.

9.7 Rendering. `shoot(scene, params, store, narration, datasets, draft)` configures Manim in `tempconfig`, renders in a temporary directory, stores the silent H.264 clip, and returns `SceneRender` with `checks = {layout, render}` and the cues played. Draft: 240 px, 15 fps. Output is byte-identical across runs: x264 runs without MB-tree, whose AVX-512 code reads uninitialized memory. Manim's global configuration and VTK are thread-unsafe; parallelize over processes.

9.8 Implementation notes.
1. `Scene.play` overwrites `self.duration`; the clip end is kept in `Clip.t_end`.
2. PyVista renders through OSMesa (`VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow`); requires `libosmesa6`.
3. Build failures are re-raised as `AnimateError` naming `scene.visual:primitive`; a failing cue names its action or start time.
4. Tests run Manim under `tempconfig` with a temporary `media_dir`.
5. `Delayed` defers `begin` to its own frame: `.animate` targets, a derivation's `last()` and morph sources depend on the state then.
6. `TransformMatchingTex` replaces source by target; `derive` tracks the step shown.
7. Cairo `Scene.remove` of a part splits its visual; `Clip.remove` and `Clip.replace` account for split parts. A `play` in which nothing moves redraws every frame, else translucent mobjects are drawn twice.
8. `show` writes TeX parts in place, without introducing them: an introduced group would split the visual and break later morphs.

9.9 Scene generation. `scene.animate(scene, data, narration, store, llm, params) -> (SceneRender, Usage)`; `data` maps request digests to `DataSet`; `Usage` sums codegen, repair and critic calls. With $\pi_5$ = (`width`, `height`, `fps`, `wpm`, `max_retries`) and $D_s = [d(\text{DataSet of } r) \text{ or null} : r \in \texttt{scene.data}]$,
$$k_{\text{animate}} = d\big([\texttt{animate}, v, d(s), d([D_s, d(\text{Narration}) \text{ or null}, \pi_5])]\big). \tag{9.4}$$

| Module | Content |
|---|---|
| `primitives.code` | static gate, `code` primitive, pinned API |
| `repair` | localized LLM patch, pitfall memory |
| `critic` | keyframes, motion and content checks, VLM verdict |
| `animate` | Algorithm 9.3, stage key |

**Algorithm 9.3 (animate).** Key hit $\Rightarrow$ return. Else:
1. $E$ ← visuals whose primitive is not in `PRIMITIVES`.
2. For at most $N_{\text{retry}}+1$ rounds: if $E \ne \emptyset$, patch $s$ by `repair` (a rejected patch leaves $s$ unchanged, appends its error to $E$, ends the round); $E$ ← first non-empty of: static gate of `code` visuals, draft render, critic. If $E = \emptyset$: final render, store under (9.4), return. Else record $E$ in pitfall memory.
3. Exhaustion raises `AnimateError` with the last $E$.

Codegen is the repair of round 1.

9.10 `code` primitive. The snippet defines `def build(array)` returning one `Mobject`, optionally `def act(m, verb, parts)` returning an animation for its own verbs; `array(i, name, part=None)` reads an `ArrayRef`. It enters and fits (9.2) like any primitive. The gate admits a whitelist (32 mobject classes, 11 animations, direction and colour constants, 14 builtins, 29 NumPy functions as `np.f`) and rejects imports, `while`, `try`, `with`, `raise`, `global`, classes, other top-level statements, and attributes with prefixes `_`, `f_`, `gi_`, `co_`, `cr_`, `ag_`, `tb_` or names `format`, `save`, `tofile`, `dump`. Execution sees exactly these symbols; errors report the snippet line. The gate filters model errors; it is no security boundary. The argument's description carries the pinned API, so planner and repair see it in the catalog.

9.11 Localization. Errors name visual $i$ of scene $s$ as `s.i:primitive`. `repair` may replace only the visuals named in $E$ (block level; snippet lines give line level), else all (scene level). The model returns `Patch` = [(index, primitive, args JSON, at)]; a patch outside the allowed indices, with non-object `args`, or yielding an invalid `Scene` is rejected. The system prompt carries catalog and region sizes, so it is cached. Patches are memoized in namespace `repair` under $H(t, \text{system}, s, E)$, $t$ the provenance tag (§4.4); pitfalls stay out of the key, so a resumed run replays its repairs.

9.12 Critic. Three checks in order; the first non-empty is returned.
1. Motion. A stretch over 8 s without a playing cue fails. An action cue fails if fewer than 24 pixels of every frame it plays change by more than 32/255 in some channel.
2. Content. Keyframes: for consecutive cue starts $a < b$,
$$n = \max\{\, m \in [a, b) : \text{no cue plays at } m \,\}, \tag{9.5}$$
kept if it exists and a visual is alive; at most 8, evenly subsampled. A live visual fails if its cell has no pixel above 16.
3. The model judges the keyframes (PNG) against the plan and returns `Verdict`.

9.13 Pitfall memory. Namespace `pitfall`, key $H(\text{primitive})$ (`scene` if unlocalized), value the last 8 distinct messages (300 characters each). Last-writer-wins; a lost entry only weakens a hint.

9.14 Notes. `code` is a catalog primitive with the same steps interface as the library. LaTeX precompile is the build phase of the draft render. Unit tests use a queued fake LLM (`tests/scene/fake.py`).

9.15 `hierarchy` primitive. Draws an `h2.rss` DataSet (§8.7) from level $\lambda$ (default $d$; `done` stages already eliminated). Plate view (2-D points): cluster boxes, grey or in their colour class, with a $k_t \mid r_t$ bar, dimmed once eliminated. Operator view: the active matrix in tree order, block widths $\propto |B_t|$; near blocks orange, far blocks blue by level (darker is coarser), fill amber, zeroed bands white, $S$ blue, $R$ red. Parts: `t` (first stage of the level with largest $|N(t)|$), `s` (its next later neighbour), `cluster:k`, `colour:c`, `block:a:b`.

| Verb | Effect |
|---|---|
| `select`, `footprint`, `ring` | mark $t$, $N(t)$, $N^2(t) \setminus N(t)$ |
| `clear`, `colour` | unmark; colour $t$, a class or the level by $c(t)$ |
| `rotate`, `split`, `zero`, `eliminate`, `schur`, `fill` | phases 1–6 of stage $t$: flash rows and columns; split $S \mid R$; zero $R$; shrink to $k_t$; flash $N(t)^2$; show fill |
| `drop` | remove a fill block, flashing it and its pair |
| `wave` | eliminate the pending stages of a colour |
| `coarsen` | finish the level, merge children into parents |
| `top` | one dense block on the top level |

`advance` maps (state, step) to the next state and its flashes, rejecting part kinds a verb does not take (`TAKES`). `draw` maps a state to keyed specs. The `Board` holds the state; `go(steps)` returns one `AnimationGroup` of one `Transform` per changed key. A vanishing block morphs into its parent's block, a box into its parent box; the rest fades. Items are created invisible on first use. `steps` are cues at $t_0 + (i+1)(t_1-t_0)/(n+1)$; steps closer than 0.1 s raise `AnimateError`. Steps and actions advance the state in play order; a resumed view replays steps before actions, so a visual uses one or the other. Selectors resolve when the verb plays; `part` returns a board child refilled after each transition, so a part follows the walk across levels.

9.16 Decisions.

| # | Decision | Reason |
|---|---|---|
| S1 | Motion as actions on named parts, fired at bookmarks or words | progressive graphics; one interface for library, `code`, `hierarchy` |
| S2 | Lazy cue set-up (`Delayed`) and overlap clusters | overlapping cues keep run times; animations see the current state |
| S3 | Actions clamped between entry and exit | a word spoken during the entry still fires |
| S4 | Persistent views by `persist` and `enter: none` | scene cuts change only what changes; clips stay cacheable |
| S5 | Motion and content checks before the VLM | cheap, deterministic |
| S6 | x264 without MB-tree | byte-identical clips; faster, less memory, 32 % larger files |

## 10 Narration

10.1 $\Phi_6$ maps each scene to a `Narration`: audio, duration, spoken `words` and written `captions` with times, bookmark times. Entry: `narrate.narrate(board, store, tts, verbalizer, workers) -> {scene id: digest}`.

| Module | Content |
|---|---|
| `verbalize` | prose and inline math split; `TEX` rewrites → MathML (MathJax) → speech (SRE, ClearSpeak) → `SPEECH` rewrites, one `node sre.cjs` call per run; (written, spoken) token pairs (§10.6) |
| `written` | inline TeX → Unicode for captions |
| `g2p` | espeak-ng IPA mapped to the misaki inventory, per-word alignment (Algorithm 10.2) |
| `tts` | `TTS` protocol (`id`, `rate`, `wpm`, `natural`, `synth`); `Kokoro`, `Espeak`; WAV I/O |
| `align` | timeline: trim, fades, gaps, word and bookmark times (Algorithm 10.3) |
| `proc` | subprocess call with typed failure |

10.2 Runtime: `espeak-ng` on `PATH`; `NODE_PATH` with `speech-rule-engine@4.1.4`, `mathjax-full@3.2.1`; for Kokoro, `ANIMATH_KOKORO` naming a directory with the files below. Weights are never committed.

| File | Source | SHA-256 |
|---|---|---|
| `kokoro-v1.0.onnx` | release `model-files-v1.0` of `thewh1teagle/kokoro-onnx` | `7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5` |
| `voices-v1.0.bin` | same release; npz, voice $\to 510\times1\times256$ float32 | `bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d` |
| `config.json` | `src/kokoro_onnx/config.json` of the same repository; key `vocab` | `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f` |

| Backend | Rate | Default |
|---|---|---|
| `Kokoro` | 24 kHz | voice `af_heart`, 135 wpm |
| `Espeak` (no `ANIMATH_KOKORO`) | 22.05 kHz | `en-us`, 135 wpm |

Other voices: `am_michael` (US), `bf_emma`, `bm_george` (GB; prefix `b` selects `en-gb` phonemes), and the rest of Kokoro v1.0. `voice` selects one (§12.1); without `ANIMATH_KOKORO`, a Kokoro voice name falls back to espeak-ng's default.

10.3 Cache key.
$$k = d\big(["\text{narrate}", v, d(\text{id}, \text{narration}), \text{tts.id}, \text{verbalizer.id}, \bar s]\big). \tag{10.1}$$
`tts.id` = `kokoro:` model SHA-256 prefix, voice, `wpm`, $d$(lexicon, word list, phoneme map, vocab, style); `verbalizer.id` = `sre:` domain, $d$(`TEX`, `SPEECH`). Edits to visuals, math or duration do not re-synthesize; edits to pronunciation tables do, and edits to other scenes only when they move $\bar s$ (10.2). `written` and `align` constants are covered by $v$.

10.4 Sentences and rate. Lines are joined into utterances until one ends in `.`, `!` or `?` (closing quotes and brackets allowed) or has `pause_s` $> 0$; each utterance is one `synth` call and carries the pause $p$ of its last line. A bookmark is the index of its line's first word in the utterance. The storyboard's utterances $u_1,\dots,u_K$, $n$ spoken words in all, are synthesized at one speed
$$\bar s = \frac{\text{wpm}}{60\,n}\sum_{k} N(u_k), \tag{10.2}$$
rounded to 0.01, $N(u)$ = `natural(u)` the seconds from the first word's start to the last word's end at speed 1. All words then span $60n/\text{wpm}$ s up to rounding, whatever the voice's pace, and the tempo is constant across scenes. Espeak's $N$ is nominal, so its $\bar s = 1$.

**Algorithm 10.1 (Kokoro synthesis).** Words $w_1,\dots,w_n$ of an utterance.
1. Phonemes $p_i$ by Algorithm 10.2; leading and trailing punctuation $o_i, c_i$ stays in the token stream (`;:,.!?—…"()“”`) for pauses and intonation.
2. Tokens $t = o_1 p_1 c_1 \sqcup \dots \sqcup o_n p_n c_n$, $\sqcup$ the space id. If $\lvert t\rvert > 510$, split recursively at the clause end nearest the middle.
3. The pruned graph gives the unrounded frames $d_j$ of each token of $[0, t, 0]$ at speed 1 (`/encoder/predictor/ReduceSum_output_0`); the full graph rounds them as $\delta_j(s) = \max(1, \operatorname{round}(d_j/s))$, so $\sum_j \delta_j$ jumps with $s$. `fit` scans $s \in \bar s\,[0.8, 1.2]$ in steps of $10^{-3}\bar s$ for
$$\min_s \Big\lvert \sum_j \delta_j(s) - \frac{1}{\bar s}\sum_j d_j \Big\rvert, \tag{10.3}$$
ties to the $s$ nearest $\bar s$: the utterance scales by $1/\bar s$ up to a frame. The full graph runs with style row $S_{\text{voice}}[\lvert t\rvert - 1]$ and that $s$, and outputs `/encoder/Clip_output_0`, the $\delta_j$ in frames of $h = 600$ samples.
4. With $F_j = h\sum_{k<j}\delta_k$ and $[a_i, b_i)$ the token range of $p_i$, word $i$ spans samples
$$\big[F_{a_i+1},\; F_{b_i+1}\big), \tag{10.4}$$
shifted by the leading pad token.
5. Scale by $\frac12$, round to int16.

`with_outputs` edits the serialized `ModelProto` directly (no `onnx` dependency): it appends outputs or, with `prune`, keeps only them, their ancestor nodes and the initializers those read. The pruned predictor keeps 937 of 2464 nodes and costs 3 % of a synthesis. A name no node computes raises `NarrateError`.

**Algorithm 10.2 (phonemes, `g2p.Phonemizer`).**
1. Spoken core of each word: lexicon entries as espeak mnemonics (*Schur* `[[S'Ur]]`, *Galerkin*, *Lanczos*, …); 2–4 capitals or hyphenated capitals spelled (*LU*, *RS-S*; *BLAS*, *NASA*, *RAM*, *SIAM* read as words); *A* before an operator word, a single letter or the end `[['eI]]`.
2. Clauses: maximal runs without inner punctuation. In-context IPA $c$ per clause: one `espeak-ng --ipa --tie=^` call, mapped to misaki (`COMMON | E2M[lang]`, longest match first).
3. Stand-alone IPA $s_1,\dots,s_n$ of all cores: one call, one core per line, `-l 4096`; stress marks dropped. A line count other than $n$ raises `NarrateError`.
4. espeak joins function words and expands numbers, so $c$ has no one-to-one word split. Align $b = s_1 \sqcup \dots \sqcup s_n$ with $c$ without stress marks (`difflib.SequenceMatcher`, no autojunk). The separator after $s_i$ maps exactly for `equal`, proportionally for `replace`, to the opcode start for `delete`; $c$ is cut there, a stress mark at a cut going to the next word.

Every pronounced word gets a non-empty $p_i$, hence a positive span (10.4).

**Algorithm 10.3 (timeline, `align.timeline`).** Rate $r$; utterances $k = 1,\dots,K$ with PCM $x_k$, spans (10.4), pauses $p_k$.
1. Bounds $[a_k, b_k)$: 10 ms frames with RMS above $-60$ dBFS together with the word span, widened by 50 ms, clamped; a silent utterance raises `NarrateError`. No word end is cut.
2. Raised-cosine fades of $m = 0.01r$ samples at both ends, gain $\frac12 - \frac12\cos\big(\pi (j+\frac12)/m\big)$.
3. Layout by words, $\alpha_k, \omega_k$ the first word's start and the last word's end in $x_k$: the first word at $L = 0.4$ s; the first word of $k+1$ at $G + p_k$ after $\omega_k$, $G = 0.35$ s (the planner's $g$); the end $\max(T_0, p_K)$ after $\omega_K$, $T_0 = 0.6$ s. Offsets
$$o_1 = \max(0,\ Lr - \alpha_1 + a_1), \qquad o_{k+1} = \max\big(o_k + b_k - a_k,\ o_k + \omega_k - a_k + (G + p_k)r - \alpha_{k+1} + a_{k+1}\big).$$
4. Word times $\big(o_k + \operatorname{clip}(\text{span}, a_k, b_k) - a_k\big)/r$; a bookmark is its word's start.

Offsets by words, not audio bounds, keep gaps exact (audio starts 55–165 ms before the first word). Word spans are $N(u_k)/\bar s$, so a scene of utterances $k \in I$ lasts
$$T_I = L + \frac{1}{\bar s}\sum_{k \in I} N(u_k) + \sum_{k \in I,\ k < \max I} (G + p_k) + \max(T_0, p_{\max I}) \tag{10.5}$$
up to a frame per utterance. Summed over scenes the second term is $60n/\text{wpm}$ by (10.2): the total is the planner's $E$ (§7.3).

10.5 Accuracy. Word times are the model's token durations, exact to one frame (25 ms); bookmarks are word starts, so $Q_3$ holds by construction. With (10.2)–(10.5) at 135 wpm, the spoken rate lies within 134.5–135.8 wpm across `af_heart`, `am_michael`, `bf_emma`, `bm_george` (rounding of $\bar s$), and lengths match the planner's estimate within −0.1 to +0.4 %.

10.6 Math speech and captions. `TEX` rewrites before SRE: `\mathcal H^2` → H two; two-digit subscripts spaced; upright superscript words read as words. `SPEECH` rewrites after SRE give lecture style: powers $-1$, $T$, $-T$, $*$, $H$ → inverse, transpose, inverse transpose, star, Hermitian; *raised to the k power* → to the k; fractions → over; *the metric of x sub 2* → the 2 norm of x; *script l* → ell; *O of* → order; font words, parentheses, *sub* dropped; *comma dot dot dot comma* → up to; *negative* → minus; *is a member of* → in.

| TeX | Spoken | Caption |
|---|---|---|
| `L_{21}`, `D_{RR}`, `\mathcal N(t)` | L 2 1, D R R, N of t | L₂₁, D_RR, 𝒩(t) |
| `\epsilon_L/u`, `\chi/(1-\chi)` | epsilon L over u, chi over 1 minus chi | ε_L/u, χ/(1−χ) |
| `\mathcal H^2`, `\|A^{-1}\|_2` | H two, the 2 norm of A inverse | ℋ², ‖A⁻¹‖₂ |

`Verbalizer.tokens` splits each line at prose whitespace into source tokens $\tau_1,\dots,\tau_q$ (a formula with touching punctuation is one token), each with written and spoken form. `written(tex)` is a recursive descent over TeX tokens: Greek letters and operators as symbols; `\mathcal`, `\mathbb` letters; Unicode sub- and superscripts when every character has one and the script is no word of three or more letters, else `_max`, `_(i,j)`; `\frac{a}{b}` as $a/b$; accents as combining marks; `\left`, `\right`, fonts and environments dropped. With $n_j$ spoken words in $\tau_j$ and $N_j = \sum_{i\le j} n_i$, caption $j$ spans
$$\big[\text{start}(w_{N_{j-1}+1}),\; \text{end}(w_{N_j})\big], \tag{10.6}$$
so caption boundaries are token boundaries; tokens without spoken words are dropped. `words` serve bookmarks and $Q_3$; `captions` feed the subtitles (§11.3).

10.7 Concurrency. All formulas are verbalized in one subprocess; a pool of `workers` threads runs `natural` on every utterance for (10.2) and synthesizes the scenes missing from the store. Both ONNX sessions are shared (thread-safe `run`) with fixed `intra_op_num_threads`; `natural` and `synth` are stateless.

## 11 Assembly

11.1 Interface. `assemble.assemble(store, board, renders, narrations, threads=1) -> str` maps the digests of a `Storyboard`, its `SceneRender`s and `Narration`s (matched by `scene_id`) to a `Manifest` digest. Key $d([\texttt{assemble}, v, p, d_{\mathcal{B}}, d^R_1,\dots,d^R_N, d^N_1,\dots,d^N_N])$ in scene order, $p$ = threads.

11.2 Timeline. Scene $i$ has render duration $d^R_i$, narration duration $d^N_i$, common frame rate $f$, audio rate $R = 48$ kHz. With $d_i = \max(d^R_i, d^N_i)$,
$$n_i = \lceil f d_i - 10^{-6} \rceil,\qquad T_i = \frac{1}{f}\sum_{j<i} n_j,\qquad S_i = \operatorname{round}(R\,T_{i+1}) - \operatorname{round}(R\,T_i). \tag{11.1}$$
Segment $i$ has exactly $n_i$ frames and $S_i$ samples, so audio–video drift stays below one sample. Subtitle times are word times plus $T_i$.

**Algorithm 11.1 (assemble).**
1. Load artifacts; renders and narrations must cover the scenes bijectively.
2. Probe clips: equal width, height, $f$; probed and claimed durations within 0.1 s.
3. Compute (11.1); build WebVTT (§11.3).
4. Loudness pass 1: `loudnorm` measures integrated loudness $I$ (EBU R128) and true peak of the concatenated narration; silence is an error.
5. Pass 2, one `ffmpeg` call: per clip `fps`, `tpad`, `trim` to $n_i$; per narration resample to $R$ mono, `apad`, `atrim` to $S_i$; `concat`; gain $-16 - I$ dB, then `alimiter` (ceiling $-2.5$ dBFS, attack 5 ms, release 80 ms, look-ahead); H.264 High, yuv420p, CRF 18, AAC 160 kb/s, faststart, bitexact, metadata stripped.
6. Verify: h264, aac at $R$, duration within 0.1 s of $T_N$; measure loudness and true peak (pass 3). Store video, subtitles, `Manifest`.

Linear `loudnorm` would need true peak minus loudness below 14.5 dB; speech exceeds it (Kokoro ≈ 20 dB), forcing the pumping dynamic mode. One fixed gain plus a transient limiter keeps $I$ within 1 LU of target and the true peak below $-1.5$ dBTP after AAC.

11.3 Subtitles. Caption tokens (§10.6; words if none) are grouped greedily into cues, closed at a token ending in `. ? ! ; :`, before 84 characters, or before 6 s; cues over 42 characters wrap once near the middle; text is HTML-escaped. A cue never splits a formula.

11.4 Manifest. `artifacts` = {`storyboard`, `render/<id>`, `narration/<id>`}; `versions` = {`assemble`, `ffmpeg`}; `timings_s.assemble`; `metrics` = {`duration_s`, `loudness_in_lufs`, `true_peak_in_dbtp`, `loudness_out_lufs`, `true_peak_out_dbtp`}. The orchestrator adds stage usage.

11.5 Notes. Clip audio is ignored. Output bytes are reproducible for fixed inputs, ffmpeg build and $p$ ($p$ changes x264 output, hence in the key). Requires `ffmpeg`, `ffprobe` with libx264. Blobs pass to ffmpeg by store path; only the output uses a temporary directory.

## 12 Orchestration and evaluation

12.1 Interface. `pipeline.Pipeline(settings, llm, tts, verbalizer, animate, fetch, check)`; `run(bundle, edit=None, part=None) -> Manifest | Paused`. One method per stage. `animate` defaults to `scene.animate`; `pipeline.render_only` renders the primitive library without LLM. `tts(params)` defaults to `voice`: Kokoro at `$ANIMATH_KOKORO`, else espeak-ng, at `wpm` (§10.2).

**Algorithm 12.1 (run).**
1. $\mathcal D = \Phi_1(\mathcal S)$; if `part`, restrict $\mathcal D$ (Algorithm 12.2).
2. $\mathcal K = \Phi_2(\mathcal D)$; gate (§12.3).
3. $\mathcal B = \Phi_3(\mathcal K, \pi)$ with `scene.catalog()` and kernel schemas; gate.
4. $\Phi_4 \parallel \Phi_6$ on two threads, each with `workers` threads.
5. $\Phi_5$ per scene, cached under
$$k_s = d\big([\texttt{animate}, v, f, d(s), d(N_s), d(\pi_5), d(D_{s,1}), \dots]\big), \tag{12.1}$$
$f$ the animate function's qualified name, $\pi_5$ = (`width`, `height`, `fps`, `style`, `seed`, `max_retries`), $D_{s,i}$ the scene's datasets. Misses run in a `spawn` pool of $\min(p, \#\text{misses})$ processes, inline if $p = 1$ or one miss; workers rebuild store and LLM from `Settings`.
6. $\Phi_7$; the manifest gains `source`, `doc`, `graph`, `dataset/<request>` digests, versions, timings, summed usage and automatic metrics.

12.2 Selection. `bundle(path, params, store, pages)`: a PDF alone, MD with sibling `.bib`, LaTeX with its tree (`.tex .bib .bbl .sty .cls`). `pages("3-7,9")` copies 1-based pages by pdfium and fixes the trailer `/ID` to $d(\text{bytes}, \text{indices})$, so the bundle digest is reproducible.

**Algorithm 12.2 (section).** Components split by `/`; `2.3.1` expands to ordinals $2, 3, 1$, any other component is a case-folded title substring. Start with all blocks. Per key: among headings strictly inside the range take those of minimal level; pick the $k$-th or the first matching; the range becomes that heading up to the next of the same level. Refs outside the range are dropped (bibliography kept); title = document title and chosen headings joined by `/`. No match raises `PipelineError`.

12.3 Gates (F12). With `approval_gates`, after $\Phi_2$ and $\Phi_3$ the artifact $a$ is looked up under $d([\texttt{gate}, \text{kind}, d(a)])$; a hit continues with the approved digest, possibly an edited artifact. A miss returns `Paused(kind, d(a))` unless `edit` is given: `''` approves $a$, JSON text approves the validated replacement. Stages are cached, so resuming re-runs nothing.

| Step | CLI |
|---|---|
| review $\mathcal K$ | `animath run src` → `{"paused": "graph", "digest": d}`; `animath inspect graph d` |
| approve | `animath run src --approve`, or `--edit graph.json` |
| review, approve $\mathcal B$ | same, kind `storyboard` |

12.4 Budget (N9). After each LLM stage, usage $u$ costs $c = p\cdot u / 10^6$ USD with per-MTok prices $p$ (input, output, cache read, cache write) from `PRICES` (`claude-opus-5-5`: 4, 20, 0.2, 5). $c >$ `budget_usd` raises `PipelineError`; a model without prices raises when a budget is set.

12.5 Evaluation. `eval.evaluate(store, manifest, expected, llm)` computes the metrics of §1.4 from the manifest's inputs (`eval.metrics`, `eval.formula`, `eval.judge`); `metrics.failures` lists metrics missing their target. The $Q_7$ judge scores 4 rubric items (1–5) on the storyboard, source equations and 8 keyframes (768 px; for $t_j = (j+\frac12)T/8$, the frame in $[t_j - 1, t_j + 1]$ s of least change from its predecessor, nearest $t_j$ on ties).

**Algorithm 12.3 (formula tracing).** Normalization: drop spacing and sizing commands (`\,`, `\quad`, `\left`, `\big`, …) and `&`; tokenize into control words, control symbols and characters; unwrap braces around one token; strip trailing `.,;`; compare token sequences. Equivalence: SymPy `parse_latex` (Lark, font commands removed), all readings of an ambiguous parse; equalities $a = b$, $c = d$ agree iff $(a-b) \mp (c-d)$ simplifies to 0, expressions iff $a - b$ does. Verdict: True if some pair agrees, False if none, None if a side does not parse. Shown formulas: `math`, `equation`, `derive` steps (markers `{{…}}` removed). References: equations and inline math of $\mathcal D$ with their items (split at `,`, `;`, `\\` outside brackets; `gathered`, `aligned`, `split` dropped). A formula is traced iff it matches a reference, all its items do, or, as a derive step, it is equivalent to its predecessor. Implemented in `core.formula`; the planner applies it (Algorithm 7.3).

12.6 Golden run. With `ANIMATH_API_KEY` set, or in session mode, per case: `animath run <source> -p approval_gates=false`, then `animath eval <manifest> --expected tests/golden/<case>/expected.json --judge`.

12.7 Decisions.

| # | Decision | Reason |
|---|---|---|
| E1 | Section and page selection in the orchestrator | no contract change |
| E2 | Gate approvals keyed by artifact digest | stable under caching; edits are plain artifacts |
| E3 | $\Phi_5$ in spawned processes | Manim and VTK globals; `fork` after threads is unsafe |
| E4 | SymPy verdict three-valued | the Lark grammar covers a subset of LaTeX |
| E5 | $Q_7$ from storyboard and keyframes, not audio | narration text is in the storyboard |

## 13 Performance

Figures on 4 CPU cores, no GPU.

| Item | Value |
|---|---|
| `make check` | ≈ 3 min |
| pandoc call | ≈ 10 ms |
| Numerics, largest admissible request | quadrature convergence 0.8 s; EFIE $ka=50$, $n=2048$ 2.3 s; DLP $n_{\max}=1024$ 3.8 s; GMRES $n=1024$, $m=256$ 1.2 s; CG $n=1024$ 0.4 s |
| `h2.rss`, $n = 4096$, `tol` 1e-5 | factorisation 3.2 s; 8 s with dense reference |
| Planner formula check | ≈ 2.5 s per first draft; ≈ 0.04 s per repair (verdicts cached) |
| Draft render, 12 s scene, 8 primitives | ≈ 10.5 s |
| `hierarchy`, $n = 4096$, 1080p30 | ≈ 4.1 s per second of video |
| `hierarchy`, $n = 4096$, 240p15 draft | ≈ 0.12 s per redrawn frame |
| x264 without MB-tree, 20 s 1080p30 scene | 19.7 s render, 0.55 GB peak |
| Kokoro | load ≈ 6 s; synthesis ≈ 0.55 × real time with 4 threads |
| espeak-ng, two lines, three formulas | 0.74 s cold |
| Assembly, 3 × 10 s 1080p60 clips, $p = 4$ | 34 s |
| Pipeline, two scenes at 320×240 through the process pool | ≈ 7 s |

## 14 Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | CPU-only toolchain; PDF transcription by Claude vision instead of GPU parsers | no GPU (N11) |
| D2 | `requirements.lock` (uv export) instead of `uv.lock` | compact (uv.lock 177 kB) |
| D3 | Numerics in NumPy/SciPy without Numba | largest request < 4 s; `hankel2` lacks Numba support |
| D4 | `h2.rss` is textbook strong RS-S: $\eta = 2.5$, greedy distance-2 colouring, fill recompressed with the far field | reference method; variants derive from the DataSet |
| D5 | GEMMs in `h2` through SciPy's BLAS | NumPy and SciPy OpenBLAS pools contend (≈ 8× slower) |
| D6 | Self-term of (8.7) is the exact cell integral | bounded, mesh-consistent diagonal |
| D7 | `hierarchy` morphs keyed items by per-item `Transform`s | `Scene.add` dissolves groups not yet in the scene |
| D8 | External arrays enter as `data.npz` by path and SHA-256 | no new kernel needed; the hash pins cache and content |
| D9 | `hierarchy` advances a live state as steps and actions play | word-timed actions fire in play order; continued views replay them |
| D10 | BSD 3-Clause licence | open use; GPL/AGPL dependencies excluded (`make licenses`) |
