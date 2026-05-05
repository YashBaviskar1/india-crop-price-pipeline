# syntax=docker/dockerfile:1.6
FROM python:3.13-slim

# Set work directory
WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY ingestion_script/ ./ingestion_script/
COPY dataset/ ./dataset/
COPY pyproject.toml ./ingestion_script/pyproject.toml
COPY .env .env

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r <(python3 -m pip install pip-tools && pip-compile ingestion_script/pyproject.toml --output-file=-)

# Set environment variables (optional, for GCS etc.)
# ENV HISTORICAL_DATA_DIR=/app/dataset/Historical_Data/parquet
# ENV GCS_RAW_BUCKET=your-bucket-name

# Default command (can be overridden)
ENTRYPOINT ["python", "-m", "ingestion_script.backfill_historical"]

# Example usage:
# docker build -t ingestion-script .
# docker run --env-file .env ingestion-script --year 2015 --dry-run
