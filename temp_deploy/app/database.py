from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database URL - Load from environment variables
# Format: postgresql://username:password@host:port/database
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a scoped session factory
Session = scoped_session(SessionLocal)

# Base class for models
Base = declarative_base()

def get_db():
    """Dependency that provides a database session"""
    db = Session()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize the database by creating all tables.
    
    Call this function during application startup.
    """
    from .auth import models  # Import models to ensure they are registered with SQLAlchemy
    Base.metadata.create_all(bind=engine)
