FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install ".[server]"

USER 65532:65532
EXPOSE 8000

CMD ["uvicorn", "contribcheck.api:app", "--host", "0.0.0.0", "--port", "8000"]
