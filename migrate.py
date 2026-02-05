import sqlite3
import psycopg2
from psycopg2.extras import execute_values

# 1. Setup Connections
sqlite_conn = sqlite3.connect('./transport.db') # Your sqlite filename
pg_conn = psycopg2.connect("postgresql://postgres.dnzdntduisslsnxvgxzk:s9xueAtMcOJLqAmQ@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres")

def migrate_table(table_name, columns):
    print(f"Migrating {table_name}...")
    sl_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()

    # 1. We wrap column names in double quotes to handle reserved words like "order"
    # This turns: id, order  -> into -> "id", "order"
    escaped_columns = [f'"{c}"' for c in columns]
    column_str = ", ".join(escaped_columns)

    # Get data from SQLite
    sl_cursor.execute(f"SELECT {column_str} FROM {table_name}")
    rows = sl_cursor.fetchall()

    # Push to Supabase
    # We use the same escaped columns for the INSERT query
    query = f"INSERT INTO {table_name} ({column_str}) VALUES %s"
    execute_values(pg_cursor, query, rows)
    
    pg_conn.commit()
    print(f"Successfully moved {len(rows)} rows to {table_name}")

# 2. Run Migration in order (to respect Foreign Keys)
try:
    migrate_table("routes", ["id", "name", "bus_type"])
    migrate_table("directions", ["id", "route_id", "direction", "sub_name", "tik_price", "distance", "gpx", "gpx_path"])
    migrate_table("stops", ["id", "name", "lat", "lng"])
    migrate_table("route_stops", ["id", "direction_id", "stop_id", "order", "distance_from_start"])
    
    print("--- ALL DATA MIGRATED ---")
finally:
    sqlite_conn.close()
    pg_conn.close()