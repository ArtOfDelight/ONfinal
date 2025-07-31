# Use official Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    fonts-liberation libasound2 libatk1.0-0 libc6 \
    libcairo2 libcups2 libdbus-1-3 \
    libexpat1 libfontconfig1 libgcc1 \
    libgconf-2-4 libgdk-pixbuf2.0-0 \
    libglib2.0-0 libgtk-3-0 \
    libnspr4 libnss3 \
    libpango-1.0-0 libpangocairo-1.0-0 \
    libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxcursor1 libxdamage1 \
    libxext6 libxfixes3 libxi6 libxrandr2 \
    libxrender1 libxss1 libxtst6 \
    lsb-release xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and its dependencies
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium

# Copy project files
COPY . .

# Run the script
CMD ["python", "main.py"]
