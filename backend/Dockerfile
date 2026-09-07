# syntax=docker/dockerfile:1

# ---- Build stage: install Python deps into a venv ----
FROM python:3.12-slim AS builder

WORKDIR /build

# opencv-contrib-python and PyMuPDF need these system libs to build/run
# correctly even though we install the prebuilt wheels (libGL for
# opencv's GUI-adjacent symbols it links against even when headless;
# libglib for image format support).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Optional real OCR engines (PaddleOCR/EasyOCR). Off by default to
# keep the production image lean -- the app runs correctly without
# them (OCR_DEFAULT_ENGINE=stub), since app/ocr/paddle_engine.py and
# app/ocr/easyocr_engine.py import paddleocr/easyocr lazily inside
# functions, never at module load time. Build with
# `--build-arg INSTALL_OCR=true` to include them. EasyOCR additionally
# needs torch, which is NOT installed even with INSTALL_OCR=true --
# see requirements-ocr-torch-notes.txt for why (the correct wheel
# depends on whether the deployment target has an NVIDIA GPU, so it
# can't be baked into a single generic Dockerfile step).
ARG INSTALL_OCR=false
COPY requirements-ocr.txt .
RUN if [ "$INSTALL_OCR" = "true" ]; then \
        # CPU-only torch, installed FIRST and from PyTorch's own
        # dedicated CPU index (not PyPI) -- see
        # requirements-ocr-torch-notes.txt for why this matters: the
        # default PyPI torch wheel is CUDA-linked and pulls in several
        # GB of NVIDIA libraries that are not only useless on a
        # GPU-less host but were the actual root cause of repeated
        # "no space left on device" build failures. Installing this
        # explicit CPU wheel BEFORE requirements-ocr.txt means pip's
        # resolver sees torch already satisfied when it processes
        # easyocr's dependency on torch, and never reaches for PyPI's
        # CUDA build at all. ~190MB instead of several GB.
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
        pip install --no-cache-dir -r requirements-ocr.txt; \
    fi

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user -- the app never needs root, and running as root in a
# container is an unnecessary privilege-escalation surface if the app
# is ever compromised.
RUN useradd --create-home --shell /bin/bash efdi

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY --chown=efdi:efdi app ./app
COPY --chown=efdi:efdi alembic ./alembic
COPY --chown=efdi:efdi alembic.ini ./alembic.ini
COPY --chown=efdi:efdi scripts ./scripts

# uploads/, intake/, logs/ are runtime data directories, not part of
# the image's source -- created here so they exist with the right
# ownership even before a volume is mounted over them.
RUN mkdir -p uploads intake logs && chown -R efdi:efdi uploads intake logs

USER efdi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run migrations then start the server. Shell form (not exec form)
# because we need the && sequencing -- migrations must succeed before
# the server starts, and a migration failure should exit the container
# non-zero rather than serving against a stale/missing schema. `exec`
# at the front of the gunicorn line replaces the shell process with
# gunicorn itself (rather than running gunicorn as a child of the
# shell), so SIGTERM from `docker stop` reaches gunicorn directly for
# a clean graceful shutdown instead of killing the shell and leaving
# gunicorn orphaned.
CMD alembic upgrade head && \
    exec gunicorn app.main:app \
        --workers 4 \
        --worker-class uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:8000 \
        --timeout 180 \
        --access-logfile - \
        --error-logfile -
