FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install curl and system libraries required for compiling or executing dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies first to cache docker layer
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy backend application source code
COPY . /app

# Expose standard Cloud Run port
EXPOSE 8080

# Run uvicorn on 0.0.0.0 and dynamically bind to $PORT
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
