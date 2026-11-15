FROM python:3.11-slim

WORKDIR /app

# Install build dependencies for tgcrypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose default port
EXPOSE 3005

CMD ["python", "main.py"]
