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
## 10 Narration
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

## 12 Evaluation
## 13 Performance metrics

| Item | Value |
|---|---|
| `make check` wall time (WP0) | ≈ 5 s on 4 cores |
| `make check` wall time (WP5) | ≈ 12 s on 4 cores |
| Assembly, 3 × 10 s 1080p60 clips, $p=4$ | 34 s (1.15 × real time) |
| Numerics, largest admissible request per kind | rule convergence 0.8 s; EFIE $ka=50$, $n=2048$ 2.3 s; DLP $n_{\max}=1024$ 3.8 s; GMRES $n=1024$, $m=256$ 1.2 s; CG $n=1024$ 0.4 s |

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
