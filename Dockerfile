# 1. Use official Python 3.9 slim image as base
FROM python:3.9-slim

# 2. Install system libraries if needed
#    For example, install gcc, libssl-dev, etc. (just examples)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     libssl-dev \
#     && rm -rf /var/lib/apt/lists/*

# 3. Set working directory
WORKDIR /app

# 4. Copy requirements.txt into container
COPY requirements.txt /app/

# 5. Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy project source code into container
COPY . /app

# 7. Expose port 12226 (if your project needs this port)
EXPOSE 12226

# 8. When container starts, execute Python script by default
CMD ["python", "app.py"]