FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements before the source, so editing a prompt does not reinstall
# everything. This layer only rebuilds when requirements.lock changes.
#
# requirements.lock is pip freeze of the venv the tests pass in, exact
# versions. --no-deps so the container installs that set rather than
# re-resolving it, the same way sahara-code-switch does.
COPY requirements.lock ./
RUN pip install --no-cache-dir --no-deps -r requirements.lock

RUN useradd --create-home --uid 1000 ozicare && chown -R ozicare:ozicare /app
COPY --chown=ozicare:ozicare ozicare ./ozicare
USER ozicare

# Silero VAD and any other plugin weights, baked into the image so a cold
# start does not download them in the middle of a call.
RUN python -m ozicare.voice_agent download-files

# Ports come from .env (APP_PORT, AGENT_HTTP_PORT); docker-compose.yml sets
# the command for each service.
CMD ["sh", "-c", "uvicorn ozicare.main:app --host 0.0.0.0 --port ${APP_PORT:-8010}"]
