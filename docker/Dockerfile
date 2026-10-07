FROM python:3.13-slim-trixie
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-extra texlive-fonts-recommended texlive-science \
      texlive-extra-utils dvisvgm ffmpeg pandoc libcairo2-dev libpango1.0-dev pkg-config \
      espeak-ng nodejs build-essential gfortran \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.lock ./
RUN uv pip install --system -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system --no-deps .
ENTRYPOINT ["animath"]
