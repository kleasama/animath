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
## 6 Knowledge extraction
## 7 Storyboard
## 8 Numerics
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
## 10 Narration
## 11 Assembly
## 12 Evaluation
## 13 Performance metrics

| Item | Value |
|---|---|
| `make check` wall time (WP0) | ≈ 5 s on 4 cores |
| `make check` wall time (WP3) | ≈ 30 s on 4 cores |
| Draft render, 12 s scene, 8 primitives (`surface` included) | ≈ 10.5 s on 4 cores |

## 14 Decisions log

| # | Date | Decision | Reason |
|---|---|---|---|
| D1 | 2026-10-07 | Code in GitHub `kleasama/animath`; Drive holds documents only | parallel WPs need a git remote |
| D2 | 2026-10-07 | C0 defaults accepted (SPEC §8) | user approval |
| D3 | 2026-10-07 | CPU-only toolchain; GPU parsers replaced by Claude vision transcription | no GPU in containers |
| D4 | 2026-10-07 | Schemas frozen at C1; changes only through integrator | parallel WPs without conflicts |
| D5 | 2026-10-07 | Commits authored by the user, no co-author trailers | user preference |
| D6 | 2026-10-07 | `requirements.lock` instead of `uv.lock` (177 kB) | Drive transfer size |
