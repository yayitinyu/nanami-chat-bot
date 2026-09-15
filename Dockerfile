FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/bot.db \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY app ./app

EXPOSE 8080

CMD ["python", "-m", "app"]
