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

# Install runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libportaudio2 \
    alsa-utils \
    libasound2-plugins \
    libpulse0 \
    pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy VENV and App Code as root
COPY --from=builder /opt/venv /opt/venv

# Copy App Code
COPY . /app

# ONLY chmod the app directory, not the venv! This takes 0.1 seconds.
RUN chmod -R 755 /app

# Create models directory and make it writable by ANY user
RUN mkdir -p /app/assets/models && chmod -R 777 /app/assets/models
RUN mkdir -p /app/cache && chmod -R 777 /app/cache
# DO NOT set 'USER' here. We want docker-compose to decide the user at runtime.
CMD ["/opt/venv/bin/python", "main.py"]
