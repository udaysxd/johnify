import argparse
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text, inspect
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_tables(host, port, user, password, database='johnify', sslmode='require'):
    """Fix the database tables with correct schema."""
    # Construct the database URL
    db_url = f"postgresql://{user}:{quote_plus(password)}@{host}:{port}/{database}"
    
    # Configure SSL if needed
    connect_args = {}
    if sslmode:
        connect_args['sslmode'] = 'require'
    
    print(f"Connecting to: {host}:{port}/{database} as {user}")
    
    try:
        # Create SQLAlchemy engine
        engine = create_engine(
            db_url,
            connect_args=connect_args,
            echo=True  # Enable SQL query logging
        )
        
        # Test the connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ Connected to PostgreSQL: {version}")
        
        print("✅ Successfully connected to the database!")
        
        # Drop existing tables if they exist
        print("\nDropping existing tables if they exist...")
        with engine.begin() as conn:
            conn.execute(text("""
                DROP TABLE IF EXISTS user_posts CASCADE;
                DROP TABLE IF EXISTS users CASCADE;
            """))
            print("✅ Dropped existing tables")
        
        # Create users table with proper schema
        print("\nCreating 'users' table...")
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY,
                    user_name VARCHAR(100),
                    user_email VARCHAR(255) UNIQUE NOT NULL,
                    user_password VARCHAR(255) NOT NULL,
                    active VARCHAR(50) DEFAULT 'true',
                    is_verified BOOLEAN DEFAULT true,
                    created_on TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_on TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    uuid UUID
                )
            """))
            print("✅ Created 'users' table")
        
        # Create user_posts table with proper schema
        print("\nCreating 'user_posts' table...")
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_posts (
                    post_id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                    content TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("✅ Created 'user_posts' table")
        
        # Verify tables were created
        print("\nVerifying tables...")
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('users', 'user_posts')
            """))
            
            tables = [row[0] for row in result]
            print(f"Found tables: {', '.join(tables) if tables else 'None'}")
            
            if len(tables) == 2:
                print("\n✅ Database schema is now correctly set up!")
                return True
            else:
                print("\n❌ Some tables are missing after setup.")
                return False
            
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fix database tables schema')
    parser.add_argument('--host', required=True, help='Database host')
    parser.add_argument('--port', default='5432', help='Database port')
    parser.add_argument('--database', default='johnify', help='Database name')
    parser.add_argument('--user', required=True, help='Database user')
    parser.add_argument('--password', required=True, help='Database password')
    parser.add_argument('--no-ssl', action='store_false', dest='ssl', help='Disable SSL')
    
    args = parser.parse_args()
    
    success = fix_tables(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=args.password,
        sslmode='require' if args.ssl else 'disable'
    )
    
    exit(0 if success else 1)
