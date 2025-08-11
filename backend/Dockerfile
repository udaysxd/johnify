
# Use Python 3.11, not 3.12
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=8000

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    build-essential \
    cargo \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Marp CLI globally
RUN npm install -g @marp-team/marp-cli

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app code
COPY . .

RUN cat /app/app/pptx_gen.py

# Expose port
EXPOSE 8000

# Start with Gunicorn
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-b", ":8000", "app.main:app"]
