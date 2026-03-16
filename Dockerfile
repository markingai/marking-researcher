FROM python:3.12-slim

WORKDIR /app

# System dependencies for PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api/ ./api/
COPY eval_agent/ ./eval_agent/

# Copy data files
COPY "Evals_tracker - Raw data - maths.csv" .
COPY "Evals_tracker - Raw data - english .csv" .

# Copy PDF submissions (if present)
COPY Maths/ ./Maths/

# Create data directory for persistent volume mount
RUN mkdir -p /data/uploads

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
