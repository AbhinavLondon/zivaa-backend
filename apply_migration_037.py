import os
from dotenv import load_dotenv
import psycopg2

load_dotenv('c:/Users/abhin/Downloads/Zivaa Apps/zivaa-backend/.env')

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print('No DATABASE_URL found in environment or zivaa-backend/.env.')
    print('You can run this migration directly in the Supabase Dashboard SQL Editor:')
    print('https://supabase.com/dashboard/project/ecwueqoxfjcepktubqrs/sql/new')
    print('File location: zivaa-backend/migrations/037_add_preferred_language_to_patients.sql')
    exit(1)

migration_file = 'migrations/037_add_preferred_language_to_patients.sql'
with open(migration_file, 'r', encoding='utf-8') as f:
    sql = f.read()

try:
    print('Connecting to database...')
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    print('Executing Migration 037...')
    cursor.execute(sql)
    print('Migration 037 applied successfully!')
    conn.close()
except Exception as e:
    print(f'Error applying migration 037: {e}')
