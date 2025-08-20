import argparse
from urllib.parse import quote_plus
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def migrate_tables(host, port, user, password, sslmode='require'):
    """Migrate tables from 'postgres' to 'johnify' database."""
    # Source database connection (postgres)
    source_conn_str = f"host={host} port={port} dbname=postgres user={user} password={quote_plus(password)}"
    if sslmode:
        source_conn_str += f" sslmode={sslmode}"
    
    # Target database connection (johnify)
    target_conn_str = f"host={host} port={port} dbname=johnify user={user} password={quote_plus(password)}"
    if sslmode:
        target_conn_str += f" sslmode={sslmode}"
    
    print("=== Starting Database Migration ===")
    print(f"Source: postgres database on {host}")
    print(f"Target: johnify database on {host}")
    
    try:
        # Connect to source database
        print("\nConnecting to source database (postgres)...")
        source_conn = psycopg2.connect(source_conn_str)
        source_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        source_cur = source_conn.cursor()
        
        # Get list of tables in source database
        source_cur.execute("""
            SELECT table_schema, table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
        """)
        
        tables = source_cur.fetchall()
        
        if not tables:
            print("No tables found in source database.")
            return False
            
        print(f"\nFound {len(tables)} tables in source database:")
        for schema, table in tables:
            print(f"- {schema}.{table}")
        
        # Connect to target database
        print("\nConnecting to target database (johnify)...")
        target_conn = psycopg2.connect(target_conn_str)
        target_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        target_cur = target_conn.cursor()
        
        # For each table, get its structure and data
        for schema, table in tables:
            print(f"\nMigrating table: {schema}.{table}")
            
            # Get table structure
            source_cur.execute(f"""
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            
            columns = source_cur.fetchall()
            
            # Create table in target database
            create_table_sql = f"CREATE TABLE IF NOT EXISTS {table} ("
            column_defs = []
            
            for col in columns:
                col_name, data_type, char_max = col
                col_def = f"{col_name} {data_type}"
                if data_type in ['character varying', 'varchar'] and char_max:
                    col_def += f"({char_max})"
                column_defs.append(col_def)
            
            create_table_sql += ", ".join(column_defs) + ")"
            
            print(f"  Creating table {table}...")
            target_cur.execute(create_table_sql)
            
            # Copy data
            print(f"  Copying data to {table}...")
            source_cur.execute(f"SELECT * FROM {schema}.{table}")
            rows = source_cur.fetchall()
            
            if rows:
                col_names = [col[0] for col in columns]
                insert_sql = f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ("
                insert_sql += ", ".join(["%s"] * len(col_names)) + ")"
                
                target_cur.executemany(insert_sql, rows)
                print(f"  Copied {len(rows)} rows to {table}")
            else:
                print(f"  No data to copy for {table}")
        
        print("\n✅ Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        return False
    finally:
        if 'source_cur' in locals():
            source_cur.close()
        if 'source_conn' in locals():
            source_conn.close()
        if 'target_cur' in locals():
            target_cur.close()
        if 'target_conn' in locals():
            target_conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Migrate tables from postgres to johnify database')
    parser.add_argument('--host', required=True, help='Database host')
    parser.add_argument('--port', default='5432', help='Database port')
    parser.add_argument('--user', required=True, help='Database user')
    parser.add_argument('--password', required=True, help='Database password')
    parser.add_argument('--no-ssl', action='store_false', dest='ssl', help='Disable SSL')
    
    args = parser.parse_args()
    
    success = migrate_tables(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        sslmode='require' if args.ssl else 'disable'
    )
    
    exit(0 if success else 1)
