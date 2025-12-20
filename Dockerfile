FROM python:3.11-slim

# Install ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Python app
COPY restream.py .

# Expose port
EXPOSE 8000

# Start the app
CMD ["python", "restream.py"]