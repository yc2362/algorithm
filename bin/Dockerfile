
# Build an isolated Python runtime for Google Cloud Run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install only the dependencies needed to serve requests.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Use a non-root process in the deployed container.
RUN useradd --uid 10001 --create-home appuser
COPY --chown=appuser:appuser main.py ./
USER appuser

EXPOSE 8080

# Shell-form CMD expands Cloud Run's injected PORT variable.
CMD exec gunicorn --bind "0.0.0.0:${PORT}" --workers 1 --threads 4 --timeout 30 main:app

