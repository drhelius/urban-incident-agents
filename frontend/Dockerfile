FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=20

COPY pyproject.toml README.md ./
COPY frontend ./frontend
COPY orchestrator ./orchestrator

RUN pip install --no-cache-dir --retries 20 --timeout 300 ".[frontend,observability]"

EXPOSE 8501
CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501"]