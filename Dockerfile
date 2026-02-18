# ==========================================
# Stage 1: Builder
# ==========================================
FROM python:3.11-slim AS builder

# 1. System build deps (for compiling PyAudio)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    alsa-utils \
    libasound2 \
    libasound2-plugins \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Create the virtual environment in a GLOBAL location
# We use /opt/venv to avoid confusion with the /app working directory
RUN python -m venv /opt/venv

# 3. Install dependencies into that specific venv
# We invoke pip via the full path to ensure we are installing INTO the venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY download_models.py .
RUN /opt/venv/bin/python download_models.py

# ==========================================
# Stage 2: Runtime
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# 1. Install runtime libs (ffmpeg, libportaudio2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libportaudio2 \
    alsa-utils \
    libasound2-plugins \
    && rm -rf /var/lib/apt/lists/*
RUN chmod -R a+rx /usr/share/alsa
ENV ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf
# 2. Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 3. COPY the virtual environment
# We copy it to the exact same path to prevent symlink breakage
# Change ownership to appuser during the copy
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv
# 4. Copy application code
COPY --chown=appuser:appuser . .
RUN chown appuser:appuser /app
RUN chmod 750 /app
# 5. The Critical Fix: Explicit Command
# instead of relying on ENV PATH, we point directly to the python binary
# that contains your libraries.
USER appuser

# USER root
CMD ["/opt/venv/bin/python", "main.py"]
