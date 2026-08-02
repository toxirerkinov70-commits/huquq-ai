FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

WORKDIR /app

# curl for the health probe, bash for the shell scripts kept for manual use
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*

# the CPU wheel is several gigabytes smaller than the default torch build, which drags
# in nvidia libraries that are dead weight on this machine
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.13.0

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY docs/legal ./docs/legal
# the scheduler runs these as subprocesses
COPY parser ./parser
COPY scripts ./scripts

# an unprivileged account owns the writable paths: a process that only ever reads the
# corpus and appends to one database has no business running as root
RUN useradd --create-home --uid 10001 huquq \
    && mkdir -p /app/data /models \
    && chown -R huquq:huquq /app /models
USER huquq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
