from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database URL - Load from environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create an inspector
inspector = inspect(engine)

# Get columns for user_posts table
print("\nColumns in user_posts table:")
for column in inspector.get_columns('user_posts', schema='public'):
    print(f"Name: {column['name']}, Type: {column['type']}, Nullable: {column['nullable']}")

# Get primary key for user_posts table
print("\nPrimary key for user_posts table:")
print(inspector.get_pk_constraint('user_posts', schema='public'))

# Get foreign keys for user_posts table
print("\nForeign keys for user_posts table:")
print(inspector.get_foreign_keys('user_posts', schema='public'))
