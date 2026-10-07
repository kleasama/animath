---
title: Method of moments for the EFIE
---

# Electric field integral equation {#sec:efie}

Let $S$ be a perfectly conducting surface with unit normal $\hat{\mathbf n}$, illuminated by
$\mathbf E^{\mathrm{inc}}$. The surface current $\mathbf J$ satisfies [@harrington1968]

$$
\hat{\mathbf n}\times\mathcal T\mathbf J=-\hat{\mathbf n}\times\mathbf E^{\mathrm{inc}},\quad
\mathcal T\mathbf J=-\mathrm j\omega\mu\int_S G\,\mathbf J\,\mathrm dS'
+\frac{1}{\mathrm j\omega\varepsilon}\nabla\int_S G\,\nabla'\cdot\mathbf J\,\mathrm dS',
\label{eq:efie}
$$

with $G(\mathbf r,\mathbf r')=\mathrm e^{-\mathrm jk|\mathbf r-\mathbf r'|}/(4\pi|\mathbf r-\mathbf r'|)$.

# Galerkin discretization {#sec:mom}

Expand $\mathbf J\approx\sum_{n=1}^N I_n\mathbf f_n$ in RWG functions [@rao1982] and test
\eqref{eq:efie} with $\mathbf f_m$, $m=1,\dots,N$:

$$
\mathbf Z\mathbf I=\mathbf V,\qquad
Z_{mn}=\langle\mathbf f_m,\mathcal T\mathbf f_n\rangle,\quad
V_m=-\langle\mathbf f_m,\mathbf E^{\mathrm{inc}}\rangle.
\label{eq:mom}
$$

::: {#thm:unique .theorem}
If $k$ is not an interior resonant wavenumber of $S$, then $\mathcal T$ is injective.
:::

Cost of a direct solution of \eqref{eq:mom}:

- matrix fill: $O(N^2)$;
- LU factorization: $O(N^3)$.
