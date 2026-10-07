FROM python:3.13-slim-trixie
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-extra texlive-fonts-recommended texlive-science \
      texlive-extra-utils dvisvgm ffmpeg pandoc libcairo2-dev libpango1.0-dev pkg-config \
      espeak-ng nodejs npm build-essential gfortran libosmesa6 curl \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g speech-rule-engine@4.1.4 mathjax-full@3.2.1
ENV NODE_PATH=/usr/local/lib/node_modules ANIMATH_KOKORO=/opt/kokoro
ARG HF=https://huggingface.co
RUN mkdir -p /opt/kokoro/voices \
    && curl -fsSL -o /opt/kokoro/model.onnx $HF/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/onnx/model.onnx \
    && curl -fsSL -o /opt/kokoro/config.json $HF/hexgrad/Kokoro-82M/resolve/main/config.json \
    && curl -fsSL -o /opt/kokoro/voices/af_heart.bin $HF/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices/af_heart.bin
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.lock ./
RUN uv pip install --system -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system --no-deps .
ENTRYPOINT ["animath"]
