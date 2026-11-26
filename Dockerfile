FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install CPU-optimized packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Wrapper to safely handle literal '${PORT:-8000}' if Koyeb or another orchestrator passes it in raw command arguments
RUN printf '#!/usr/bin/env python3\nimport sys, os\nport = os.environ.get("PORT", "8000")\nif not port.isdigit():\n    port = "8000"\nsys.argv = [port if ("${PORT" in a or "$PORT" in a) else a for a in sys.argv]\nfrom uvicorn.main import main\nif __name__ == "__main__":\n    sys.exit(main())\n' > /usr/local/bin/uvicorn \
    && chmod +x /usr/local/bin/uvicorn

# Copy application source code
COPY . .

# Default environment configuration
ENV PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

CMD ["python", "run.py"]
