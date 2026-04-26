FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY backend/app /app/backend/app
COPY backend/assets /app/backend/assets
COPY backend/.env.example /app/backend/.env.example

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app/backend

RUN mkdir -p /app/data/audio

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
