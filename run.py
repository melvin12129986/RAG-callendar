import os
import uvicorn
import logging
from app.config import settings

if __name__ == "__main__":
    is_dev = settings.ENVIRONMENT.lower() in ("development", "dev", "local")
    host = settings.HOST
    port = settings.PORT
    print(f"Starting {settings.APP_NAME} in [{settings.ENVIRONMENT}] mode on {host}:{port}...")
    uvicorn.run("app.main:app", host=host, port=port, reload=is_dev)
