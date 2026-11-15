import uvicorn
import logging
from app.config import settings

if __name__ == "__main__":
    is_dev = settings.ENVIRONMENT.lower() in ("development", "dev", "local")
    print(f"Starting {settings.APP_NAME} in [{settings.ENVIRONMENT}] mode...")
    print(f"Web interface running at: http://{settings.HOST}:{settings.PORT}")
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=is_dev)
