import os
from dotenv import load_dotenv

load_dotenv('c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print('No DATABASE_URL found in environment or zivaa-backend/.env.')
    print('Please run this migration directly in your Supabase Dashboard SQL Editor:')
    print('https://supabase.com/dashboard/project/ecwueqoxfjcepktubqrs/sql/new')
    print('File location: zivaa-backend/migrations/045_optimize_vitals_daily_tier1.sql')
else:
    import psycopg2
    migration_file = 'migrations/045_optimize_vitals_daily_tier1.sql'
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()
    try:
        print('Connecting to database...')
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        print('Executing Migration 045 (Tier 1 Safe Hotfix)...')
        cursor.execute(sql)
        print('Migration 045 applied successfully!')
        conn.close()
    except Exception as e:
        print(f'Error applying migration 045: {e}')
