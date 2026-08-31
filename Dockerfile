FROM python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217

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
