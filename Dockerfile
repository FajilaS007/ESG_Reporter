FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies via pip (not apt)
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn==0.30.1 \
    httpx==0.27.0 \
    groq==0.9.0 \
    pydantic==2.11.5 \
    python-dotenv==1.0.1

# Copy application code
COPY app/ ./app/
COPY frontend/ ./frontend/

# Create cache directory
RUN mkdir -p ./app/cache

EXPOSE 8000

# Secrets passed at runtime via -e flags, never baked in
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
