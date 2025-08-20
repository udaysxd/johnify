from sqlalchemy import create_engine, inspect, text
import os
import argparse
from urllib.parse import urlparse, quote_plus, urlunparse
import sys

def create_engine_from_args(args):
    """Create SQLAlchemy engine from command line arguments."""
    if args.connection_string:
        # Parse and clean up the connection string
        parsed = urlparse(args.connection_string)
        
        # Handle Cloud SQL Unix socket format
        if parsed.path.startswith('/cloudsql/'):
            # This is a Cloud SQL Unix socket connection
            db_url = f"postgresql+pg8000://{parsed.username}:{parsed.password}@/{parsed.path.split('/')[-1]}?unix_sock={parsed.path}/.s.PGSQL.5432"
            print(f"Connecting to Cloud SQL via Unix socket: {parsed.path}")
        else:
            # Standard PostgreSQL connection
            db_url = args.connection_string
            print(f"Connecting to: {parsed.hostname}:{parsed.port or '5432'}/{parsed.path.lstrip('/')} as {parsed.username}")
    else:
        # Build connection string from individual parameters
        if not all([args.host, args.database, args.user, args.password]):
            raise ValueError("Missing required connection parameters. Either provide --connection-string or all of --host, --database, --user, and --password")
        
        db_url = f"postgresql://{args.user}:{quote_plus(args.password)}@{args.host}:{args.port or '5432'}/{args.database}"
        print(f"Connecting to: {args.host}:{args.port or '5432'}/{args.database} as {args.user}")
    
    # Create SQLAlchemy engine with appropriate parameters
    return create_engine(
        db_url,
        connect_args={
            'options': f'-c search_path={args.schema or "public"}',
            'sslmode': 'require' if args.ssl else 'prefer'
        },
        echo=True  # Enable SQL query logging
    )

# Set up command line argument parsing
parser = argparse.ArgumentParser(description='Check database schemas and tables')

# Connection string option
parser.add_argument('--connection-string', 
                   help='Full database connection string (e.g., postgresql://user:pass@host/db)')

# Individual connection parameters
parser.add_argument('--host', help='Database host')
parser.add_argument('--port', help='Database port (default: 5432)')
parser.add_argument('--database', help='Database name')
parser.add_argument('--user', help='Database user')
parser.add_argument('--password', help='Database password')
parser.add_argument('--schema', default='public', help='Database schema (default: public)')
parser.add_argument('--ssl', action='store_true', help='Use SSL for the connection')

args = parser.parse_args()

# Create the database engine
engine = create_engine_from_args(args)

# Create an inspector
inspector = inspect(engine)

def find_tables_across_schemas(table_names):
    """Search for specific tables across all schemas."""
    print("\n=== Searching for Tables Across All Schemas ===")
    found_tables = []
    
    # Get all schemas
    schemas = inspector.get_schema_names()
    print(f"Searching in {len(schemas)} schemas...")
    
    for schema_name in schemas:
        print(f"\nChecking schema: {schema_name}")
        print("-" * 50)
        
        try:
            # Get all tables in the schema
            tables = inspector.get_table_names(schema=schema_name)
            
            for table_name in tables:
                if table_name.lower() in [t.lower() for t in table_names]:
                    print(f"✅ Found table: {schema_name}.{table_name}")
                    found_tables.append((schema_name, table_name))
                    
                    # Get and print column info
                    try:
                        columns = inspector.get_columns(table_name, schema=schema_name)
                        print("  Columns:")
                        for col in columns:
                            print(f"    - {col['name']} ({col['type']})")
                    except Exception as e:
                        print(f"    Could not get columns: {str(e)}")
                    print()
        except Exception as e:
            print(f"  Error accessing schema {schema_name}: {str(e)}")
    
    if not found_tables:
        print("\n❌ None of the specified tables were found in any schema.")
    else:
        print(f"\n✅ Found {len(found_tables)} matching tables across all schemas.")
    
    return found_tables

if __name__ == "__main__":
    try:
        with engine.connect() as conn:
            # Check if we can connect
            print("✅ Successfully connected to the database!")
            
            # Check current search path and user info first
            print("\n=== Database Information ===")
            result = conn.execute(text("SHOW search_path;"))
            print(f"Current search_path: {result.scalar()}")
            
            result = conn.execute(text("SELECT current_user, current_database();"))
            user, db = result.fetchone()
            print(f"Current user: {user}")
            print(f"Current database: {db}")
            
            # Search for our specific tables
            tables_to_find = ['users', 'user_posts']
            found_tables = find_tables_across_schemas(tables_to_find)
            
            if found_tables:
                print("\n=== Summary of Found Tables ===")
                for schema, table in found_tables:
                    print(f"- {schema}.{table}")
                
                print("\nTo use these tables, you may need to update your SQLAlchemy models")
                print(f"with the correct schema, e.g.: __table_args__ = {{'schema': 'schema_name'}}")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        raise  # Re-raise to see full traceback
