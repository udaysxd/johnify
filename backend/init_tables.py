from sqlalchemy import create_engine, text, inspect
import os
import sys
import argparse
from urllib.parse import quote_plus
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Set up argument parsing
parser = argparse.ArgumentParser(description='Initialize database tables')
parser.add_argument('--host', required=True, help='Database host')
parser.add_argument('--port', default='5432', help='Database port')
parser.add_argument('--database', required=True, help='Database name')
parser.add_argument('--user', required=True, help='Database user')
parser.add_argument('--password', required=True, help='Database password')
parser.add_argument('--ssl', action='store_true', help='Use SSL for the connection')
args = parser.parse_args()

# Construct the database URL
db_url = f"postgresql://{args.user}:{quote_plus(args.password)}@{args.host}:{args.port}/{args.database}"

# Create SQLAlchemy engine
engine = create_engine(
    db_url,
    connect_args={
        'options': '-c search_path=public',
        'sslmode': 'require' if args.ssl else 'prefer'
    },
    echo=True
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Import models to ensure they're registered with SQLAlchemy
# This must be done after creating Base
from app.auth.models import User, UserPost  # noqa

def init_db():
    """Initialize the database by creating all tables."""
    print("Creating database tables...")
    
    try:
        # Create all tables defined in SQLAlchemy models
        Base.metadata.create_all(bind=engine)
        print("Successfully created database tables!")
        return True
    except Exception as e:
        print(f"Error creating database tables: {e}")
        return False

def check_tables():
    """Check if the required tables exist."""
    required_tables = ['users', 'user_posts']
    
    with engine.connect() as conn:
        try:
            # Get all tables in public schema
            result = conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            existing_tables = {row[0] for row in result}
            
            # Check which required tables are missing
            missing_tables = [t for t in required_tables if t not in existing_tables]
            
            if missing_tables:
                print(f"Missing tables: {', '.join(missing_tables)}")
                return False
                
            print("All required tables exist!")
            return True
            
        except Exception as e:
            print(f"Error checking tables: {e}")
            return False

def main():
    print("=== Database Table Initialization ===")
    print(f"Connecting to: {args.host}:{args.port}/{args.database} as {args.user}")
    
    try:
        # Test the connection
        with engine.connect() as conn:
            print("✅ Successfully connected to the database!")
            
        # First check if tables already exist
        print("\nChecking for existing tables...")
        if check_tables():
            print("\n✅ All tables already exist. No action needed.")
            return 0
        
        # If tables don't exist, create them
        print("\nCreating missing tables...")
        if init_db():
            print("\nVerifying table creation...")
            if check_tables():
                print("\n✅ Database initialization completed successfully!")
                return 0
            else:
                print("\n❌ Some tables are still missing after initialization.")
                return 1
        else:
            print("\n❌ Failed to create database tables.")
            return 1
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
