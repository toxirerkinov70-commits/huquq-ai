FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

WORKDIR /app

# the scheduler shells out to scripts/backup.sh before every refresh, and the slim image
# ships neither curl nor bash
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*

# the CPU wheel is several gigabytes smaller than the default torch build, which drags
# in nvidia libraries that are dead weight on this machine
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
# the scheduler runs these as subprocesses
COPY parser ./parser
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
