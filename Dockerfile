# Use an official lightweight Python image
FROM python:3.11-slim

# Install system dependencies
# - tesseract-ocr: For OCR processing
# - libtesseract-dev: Tesseract development libraries
# - poppler-utils: For pdf2image (converting PDF to images)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create necessary folders
RUN mkdir -p uploads submissions instance

# Set environment variables
ENV FLASK_APP=app.py
ENV PORT=5000

# Expose the port used by the app
EXPOSE 5000

# Run the application using Gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
