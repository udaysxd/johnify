import argparse
from urllib.parse import quote_plus
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def create_tables(host, port, database, user, password, sslmode='require'):
    """Create the necessary tables directly using psycopg2."""
    # Construct connection string
    conn_string = f"host={host} port={port} dbname={database} user={user} password={quote_plus(password)}"
    if sslmode:
        conn_string += f" sslmode={sslmode}"
    
    print(f"Connecting to database: {host}:{port}/{database} as {user}")
    
    try:
        # Connect to the database
        conn = psycopg2.connect(conn_string)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        print("✅ Successfully connected to the database!")
        
        # Create users table
        print("\nCreating 'users' table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS public.users (
                user_id SERIAL PRIMARY KEY,
                user_name VARCHAR(100),
                user_email VARCHAR(255) UNIQUE NOT NULL,
                user_password VARCHAR(255) NOT NULL,
                active VARCHAR(50) DEFAULT 'true',
                is_verified BOOLEAN DEFAULT true,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create user_posts table
        print("Creating 'user_posts' table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS public.user_posts (
                post_id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES public.users(user_id) ON DELETE CASCADE,
                content TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        print("\n✅ Tables created successfully!")
        
        # Verify tables were created
        print("\nVerifying tables...")
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('users', 'user_posts')
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Found tables: {', '.join(tables) if tables else 'None'}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create database tables directly')
    parser.add_argument('--host', required=True, help='Database host')
    parser.add_argument('--port', default='5432', help='Database port')
    parser.add_argument('--database', required=True, help='Database name')
    parser.add_argument('--user', required=True, help='Database user')
    parser.add_argument('--password', required=True, help='Database password')
    parser.add_argument('--no-ssl', action='store_false', dest='ssl', help='Disable SSL')
    
    args = parser.parse_args()
    
    success = create_tables(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=args.password,
        sslmode='require' if args.ssl else 'disable'
    )
    
    sys.exit(0 if success else 1)
