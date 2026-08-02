FROM python:3.11-slim

WORKDIR /app

# System deps needed by psycopg2 (build) and sentence-transformers/torch runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Streamlit needs a writable spot for logs.log; /app is fine unless the
# image is run with a read-only filesystem, in which case mount a volume.
EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
