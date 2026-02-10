FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

CMD python -c "import os; port = int(os.environ.get(\"PORT\", 8000)); import uvicorn; uvicorn.run(\"app:app\", host=\"0.0.0.0\", port=port)"
