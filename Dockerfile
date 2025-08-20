# Use the existing backend Dockerfile
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Install system dependencies with better caching
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock && \
    apt-get update -qq && \
    apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    build-essential \
    cargo \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Marp CLI globally with caching
RUN --mount=type=cache,target=/root/.npm \
    npm install -g @marp-team/marp-cli

# Create and set working directory
WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY backend/requirements.txt .

# Create virtual environment and install dependencies in one layer
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --upgrade pip && \
    pip install --no-warn-script-location -r requirements.txt

# Final stage - use bookworm for better compatibility
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Accept cache-busting argument (from Cloud Build) and surface as ENV so it affects cache
ARG SECURITY_SHA
ENV SECURITY_SHA=${SECURITY_SHA}

# Copy only the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Install runtime system dependencies (no build tools)
RUN --mount=type=cache,target=/var/cache/apt \
    rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/archives/*

# Copy only necessary files from builder
COPY --from=builder /usr/local/bin/marp /usr/local/bin/marp

# Set work directory
WORKDIR /app

# Copy application code
COPY backend .

# Expose port
EXPOSE 8000

# Start with Gunicorn
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-b", ":8000", "app.main:app"]
