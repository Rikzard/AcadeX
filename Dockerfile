# Base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create runtime folders
RUN mkdir -p uploads submissions instance

# Environment variables
ENV FLASK_APP=app.py

# Expose (optional for docs)
EXPOSE 10000

# Start server (Render-compatible)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app"]