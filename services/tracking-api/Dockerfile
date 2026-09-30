FROM python:3.12-alpine

RUN apk add --no-cache ffmpeg tzdata

WORKDIR /app
COPY services/tracking-api/server.py /app/server.py
COPY services/tracking-api/dashboard.html /app/dashboard.html
COPY db/schema.sql /app/schema.sql

ENV PYTHONUNBUFFERED=1
EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=8 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health')"

CMD ["python", "/app/server.py"]
