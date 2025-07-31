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

# Get table names
print("Tables in database:")
print(inspector.get_table_names(schema='public'))

# Get columns for users table
print("\nColumns in users table:")
for column in inspector.get_columns('users', schema='public'):
    print(f"Name: {column['name']}, Type: {column['type']}, Nullable: {column['nullable']}")

# Get primary key for users table
print("\nPrimary key for users table:")
print(inspector.get_pk_constraint('users', schema='public'))

# Get foreign keys for users table
print("\nForeign keys for users table:")
print(inspector.get_foreign_keys('users', schema='public'))
