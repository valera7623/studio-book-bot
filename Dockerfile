FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y     gcc     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && chmod 777 /app/data

CMD ["python", "-m", "src.main"]
