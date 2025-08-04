# Use Python 3.11 slim base image
FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV DISPLAY=:99
ENV RENDER=true

# Install system dependencies for Xvfb, xauth, Playwright, and Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    wget \
    curl \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    libgbm1 \
    libxshmfence1 \
    && echo "✅ System dependencies installed successfully" \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd -r scraper && useradd -r -g scraper -G audio,video scraper \
    && mkdir -p /home/scraper/Downloads \
    && chown -R scraper:scraper /home/scraper

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Install Playwright and download Chromium
RUN pip install playwright==1.47.0 \
    && playwright install chromium \
    && playwright install-deps chromium

# Copy application code
COPY . .

# Change ownership of the app directory to the scraper user
RUN chown -R scraper:scraper /app

# Switch to non-root user
USER scraper

# Health check to ensure Playwright and Xvfb are working
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD xvfb-run python -c "import playwright; from pyvirtualdisplay import Display; print('Playwright and Xvfb are working')" || exit 1

# Run the application with Xvfb
CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1920x1080x24", "python", "zomreview.py"]