FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY apps/bot/pyproject.toml apps/bot/
COPY packages/shared/pyproject.toml packages/shared/
COPY packages/database/pyproject.toml packages/database/

# Install Python dependencies
RUN pip install --no-cache-dir \
    -e apps/bot \
    -e packages/shared \
    -e packages/database

# Copy application code
COPY apps/bot/ apps/bot/
COPY packages/shared/ packages/shared/
COPY packages/database/ packages/database/

CMD ["python", "-m", "apps.bot.src.bot"]
