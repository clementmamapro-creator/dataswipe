FROM python:3.12-slim

WORKDIR /app

COPY pipeline/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline /app/pipeline

ENV PYTHONPATH=/app

CMD ["uvicorn", "pipeline.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
