# Use the official Playwright image with all dependencies pre-installed
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
ENV RENDER=true

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

# Copy application code
COPY . .

# Change ownership of the app directory to the scraper user
RUN chown -R scraper:scraper /app

# Switch to non-root user
USER scraper

# Simplified health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import playwright; print('Playwright is working')" || exit 1

# Run the main script
CMD ["python", "main.py"]