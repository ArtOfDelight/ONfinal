# Use an official Python image with a browser-friendly OS
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Singapore

# Create app directory
WORKDIR /app

# Copy only the dependency files first
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into the container
COPY . .

# Install Chromium for Playwright
RUN playwright install chromium

# Default command
CMD ["python", "main.py"]
