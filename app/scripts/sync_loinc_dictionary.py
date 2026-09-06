import os
import asyncio
from typing import List, Dict
from dotenv import load_dotenv
import httpx
from app.config import settings

# Initialize Supabase client
from supabase import create_client, Client
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

import random
import hashlib

async def generate_embedding(text: str) -> List[float]:
    """
    Generates a deterministic 384-dimensional embedding using a seeded random number generator.
    This simulates a real text-embedding model (like Google Vertex or SentenceTransformers) 
    so you can test the PGVector search pipeline locally without requiring a 2GB PyTorch 
    installation or valid Google AI API keys.
    """
    # Create a deterministic seed based on the string
    seed_val = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
    rng = random.Random(seed_val)
    
    # Generate 384 floats between -1.0 and 1.0
    embedding = [rng.uniform(-1.0, 1.0) for _ in range(384)]
    
    # Normalize the vector for cosine similarity
    magnitude = sum(x**2 for x in embedding) ** 0.5
    normalized_embedding = [x / magnitude for x in embedding]
    
    return normalized_embedding

async def fetch_loinc_updates():
    """
    Parses the official LOINC CSV file, filters for ACTIVE records, 
    generates embeddings, and upserts them into Supabase in batches.
    """
    import csv
    import os
    
    csv_path = r"C:\Users\abhin\AppData\Local\Temp\bcdbd0e9-8b7e-4ecf-8819-0e3b8cb28d9b_Loinc_2.82.zip.d9b\LoincTableCore\LoincTableCore.csv"
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return
        
    print("Starting LOINC database sync from CSV...")
    
    concepts = []
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('STATUS') == 'ACTIVE':
                loinc_code = row.get('LOINC_NUM')
                display = row.get('LONG_COMMON_NAME')
                shortname = row.get('SHORTNAME')
                if loinc_code and display:
                    concepts.append({
                        "code": loinc_code,
                        "display": display,
                        "shortname": shortname,
                        "component": row.get('COMPONENT'),
                        "class_col": row.get('CLASS'),
                        "classtype": row.get('CLASSTYPE')
                    })
                
    print(f"Found {len(concepts)} active biomarkers to process.")
    
    batch_size = 5
    batch = []
    total_inserted = 0
    
    for i, item in enumerate(concepts):
        if i < 15000:
            continue
        loinc_code = item["code"]
        long_common_name = item["display"]
        shortname = item["shortname"]
        
        if not loinc_code or not long_common_name:
            continue
            
        if i % 1000 == 0:
            print(f"Processing {i}/{len(concepts)}: {loinc_code} - {long_common_name}")
        
        try:
            embedding = await generate_embedding(long_common_name)
            batch.append({
                "loinc_code": loinc_code,
                "long_common_name": long_common_name,
                "shortname": shortname,
                "component": item.get("component"),
                "class": item.get("class_col"),
                "classtype": item.get("classtype"),
                "name_embedding": embedding,
                "status": "ACTIVE"
            })
        except Exception as e:
            print(f"Error generating embedding for {loinc_code}: {e}")
            
        if len(batch) >= batch_size:
            for attempt in range(5):
                try:
                    supabase.table("loinc_universal_dictionary").upsert(batch, on_conflict="loinc_code").execute()
                    total_inserted += len(batch)
                    batch = []
                    await asyncio.sleep(1.0) # Add delay to prevent overwhelming Supabase
                    break
                except Exception as e:
                    if attempt == 4:
                        print(f"Failed batch after 5 attempts: {e}")
                        raise e
                    print(f"Network drop on batch. Retrying ({attempt+1}/5)...")
                    await asyncio.sleep(2 ** attempt)
    
    if batch:
        for attempt in range(5):
            try:
                supabase.table("loinc_universal_dictionary").upsert(batch, on_conflict="loinc_code").execute()
                total_inserted += len(batch)
                await asyncio.sleep(1.0)
                break
            except Exception as e:
                if attempt == 4:
                    raise e
                await asyncio.sleep(2 ** attempt)
        
    print(f"Sync complete! Inserted {total_inserted} total records.")

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(fetch_loinc_updates())
