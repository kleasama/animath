FROM python:3.13-slim-trixie
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-extra texlive-fonts-recommended texlive-science \
      texlive-extra-utils dvisvgm ffmpeg pandoc libcairo2-dev libpango1.0-dev pkg-config \
      espeak-ng nodejs npm build-essential libosmesa6 curl \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g speech-rule-engine@4.1.4 mathjax-full@3.2.1
ENV NODE_PATH=/usr/local/lib/node_modules ANIMATH_KOKORO=/opt/kokoro
ARG KOKORO=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
RUN mkdir -p /opt/kokoro && cd /opt/kokoro \
    && curl -fsSLO $KOKORO/kokoro-v1.0.onnx && curl -fsSLO $KOKORO/voices-v1.0.bin \
    && curl -fsSL -o config.json https://raw.githubusercontent.com/thewh1teagle/kokoro-onnx/main/src/kokoro_onnx/config.json \
    && printf '%s  %s\n' \
       7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5 kokoro-v1.0.onnx \
       bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d voices-v1.0.bin \
       5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f config.json \
       | sha256sum -c -
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.lock ./
RUN uv pip install --system -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system --no-deps .
ENTRYPOINT ["animath"]
