import os
from dotenv import load_dotenv

load_dotenv('c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print('No DATABASE_URL found in environment or zivaa-backend/.env.')
    print('Please run this migration directly in your Supabase Dashboard SQL Editor:')
    print('File location: zivaa-backend/migrations/041_create_zivaa_score_table.sql')
else:
    import psycopg2
    migration_file = 'c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/migrations/041_create_zivaa_score_table.sql'
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()
    try:
        print('Connecting to database...')
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        print('Executing Migration 041 (zivaa_score table + trigger + backfill)...')
        cursor.execute(sql)
        print('Migration 041 applied successfully!')
        
        # Verify
        cursor.execute('SELECT COUNT(*), AVG(mobility_score) FROM zivaa_score;')
        count, avg_score = cursor.fetchone()
        print(f'Verification: {count} rows in zivaa_score, Average Mobility Score: {avg_score}')
        conn.close()
    except Exception as e:
        print(f'Error applying migration 041: {e}')
