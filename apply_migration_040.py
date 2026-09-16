import os
from dotenv import load_dotenv

load_dotenv('c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print('No DATABASE_URL found in environment or zivaa-backend/.env.')
    print('Please run this migration directly in your Supabase Dashboard SQL Editor:')
    print('https://supabase.com/dashboard/project/ecwueqoxfjcepktubqrs/sql/new')
    print('File location: zivaa-backend/migrations/040_add_mobility_kpis_to_vitals_daily.sql')
else:
    import psycopg2
    migration_file = 'migrations/040_add_mobility_kpis_to_vitals_daily.sql'
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()
    try:
        print('Connecting to database...')
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        print('Executing Migration 040...')
        cursor.execute(sql)
        print('Migration 040 applied successfully!')
        conn.close()
    except Exception as e:
        print(f'Error applying migration 040: {e}')
