FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=20

COPY pyproject.toml README.md ./
COPY agents ./agents

RUN pip install --no-cache-dir --retries 20 --timeout 300 ".[api,observability]"

EXPOSE 8000
CMD ["uvicorn", "orchestrator.api:app", "--host", "0.0.0.0", "--port", "8000"]