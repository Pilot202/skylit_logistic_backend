from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

# Ensure models are imported so metadata is populated
import app.models  # noqa: F401
from app.database import Base


def main():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "sqlite:///./test.db")
    # If an async driver is specified (eg. +asyncpg), create a sync URL for create_all
    sync_url = database_url.replace("+asyncpg", "")

    engine = create_engine(sync_url)
    print(f"Creating tables on {sync_url}")
    Base.metadata.create_all(bind=engine)
    print("Database schema created.")


if __name__ == "__main__":
    main()
