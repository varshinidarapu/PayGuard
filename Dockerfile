FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "python scripts/init_db.py && python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
