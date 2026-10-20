FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REFUNDS_DB_PATH=/app/data/refunds.sqlite3

WORKDIR /app

COPY requirements.lock.txt ./
RUN python -m pip install --no-cache-dir -r requirements.lock.txt

COPY pyproject.toml ./
COPY refund_api ./refund_api
COPY fixtures ./fixtures
RUN python -m pip install --no-cache-dir --no-deps .

EXPOSE 8000

CMD ["uvicorn", "refund_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
