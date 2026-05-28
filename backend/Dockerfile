FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY start.sh ./start.sh
COPY worker.sh ./worker.sh

RUN chmod +x /app/start.sh /app/worker.sh

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

RUN mkdir -p /app/uploads /app/outputs && \
    useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["./start.sh"]
