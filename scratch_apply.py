import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(open("migrations/017_fhir_nullable_date.sql").read())
print("Migration applied successfully!")
