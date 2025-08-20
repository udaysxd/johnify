import psycopg2
from psycopg2 import sql
import sys

def fix_sequences(host, user, password, database='johnify', port=5432):
    conn = None
    try:
        # Connect to the database
        conn = psycopg2.connect(
            host=host,
            user=user,
            password=password,
            dbname=database,
            port=port,
            sslmode='require'
        )
        conn.autocommit = True
        cur = conn.cursor()
        
        print("Fixing sequences for users table...")
        
        # Drop and recreate the sequence with proper ownership
        cur.execute("""
        DO $$
        BEGIN
            -- Drop the existing sequence if it exists
            IF EXISTS (SELECT 1 FROM pg_sequences WHERE schemaname = 'public' AND sequencename = 'users_user_id_seq') THEN
                DROP SEQUENCE public.users_user_id_seq CASCADE;
            END IF;
            
            -- Create a new sequence
            CREATE SEQUENCE public.users_user_id_seq
                START WITH 1
                INCREMENT BY 1
                NO MINVALUE
                NO MAXVALUE
                CACHE 1;
                
            -- Set the sequence to the max user_id + 1 if there are existing users
            PERFORM setval('public.users_user_id_seq', COALESCE((SELECT MAX(user_id) FROM public.users), 0) + 1, false);
            
            -- Set the default value of the user_id column to use the sequence
            ALTER TABLE public.users 
                ALTER COLUMN user_id SET DEFAULT nextval('public.users_user_id_seq'::regclass);
                
            -- Make sure the column is not nullable
            ALTER TABLE public.users 
                ALTER COLUMN user_id SET NOT NULL;
                
            -- Set ownership of the sequence to the column
            ALTER SEQUENCE public.users_user_id_seq OWNED BY public.users.user_id;
            
            RAISE NOTICE 'Successfully fixed sequence for users table';
        END $$;
        """)
        
        print("✅ Successfully fixed sequences for users table")
        
        # Verify the fix
        cur.execute("""
            SELECT column_default 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'users' 
            AND column_name = 'user_id';
        """)
        
        default_value = cur.fetchone()[0]
        print(f"\nUser ID default value after fix: {default_value}")
        
        # Check current max user_id
        cur.execute("SELECT MAX(user_id) FROM public.users;")
        max_id = cur.fetchone()[0]
        print(f"Current maximum user_id: {max_id if max_id is not None else 'No users yet'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Fix sequence for users table')
    parser.add_argument('--host', required=True, help='Database host')
    parser.add_argument('--user', required=True, help='Database user')
    parser.add_argument('--password', required=True, help='Database password')
    parser.add_argument('--database', default='johnify', help='Database name')
    parser.add_argument('--port', type=int, default=5432, help='Database port')
    
    args = parser.parse_args()
    
    success = fix_sequences(
        host=args.host,
        user=args.user,
        password=args.password,
        database=args.database,
        port=args.port
    )
    
    if not success:
        sys.exit(1)
