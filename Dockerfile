FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./

RUN mkdir -p /app/data /app/backups \
    && chmod 700 /app/data /app/backups \
    && chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "domonap_bot.health"]

CMD ["python", "-m", "domonap_bot.main"]
