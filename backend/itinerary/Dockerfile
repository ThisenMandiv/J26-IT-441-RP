# Itinerary optimizer API (Component 2). Build and run from backend/itinerary:
#   docker build -t itinerary-api .
#   docker run --rm -p 8080:8080 itinerary-api
# Settings come from environment variables only (docs/DEPLOY.md); no secret is baked in.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# Dependencies first, so a code change does not reinstall them
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a normal user; it may write only the matrix cache folder
RUN useradd --create-home --uid 10001 app \
    && mkdir -p data/cache \
    && chown app data/cache
USER app

EXPOSE 8080
# sh expands $PORT (set by Render or Cloud Run); exec lets uvicorn receive stop signals
CMD ["sh", "-c", "exec uvicorn app.deploy:app --host 0.0.0.0 --port ${PORT:-8080}"]
