FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core libegl1 libgl1 libglib2.0-0 libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY gui ./gui
COPY tests ./tests
COPY main.py .
RUN mkdir -p /app/uploads /app/outputs /app/data /app/cache

CMD ["python", "main.py"]
