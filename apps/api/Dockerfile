FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY apps/api/pyproject.toml apps/api/
COPY packages/shared/pyproject.toml packages/shared/
COPY packages/database/pyproject.toml packages/database/

# Install Python dependencies
RUN pip install --no-cache-dir \
    -e apps/api \
    -e packages/shared \
    -e packages/database

# Copy application code
COPY apps/api/ apps/api/
COPY packages/shared/ packages/shared/
COPY packages/database/ packages/database/

EXPOSE 8000

CMD ["uvicorn", "apps.api.src.main:app", "--host", "0.0.0.0", "--port", "8000"]
