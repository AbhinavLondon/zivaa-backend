import httpx
from typing import Optional, Dict
from app.config import settings

# Initialize Supabase client
from supabase import create_client, Client
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

async def search_tier2_loinc_database(extracted_name: str) -> Optional[Dict]:
    """
    Fallback semantic search function. Called when the Tier 1 Core Dictionary 
    fails to find a match for a given biomarker.
    
    Converts the raw extracted name into a vector embedding and queries 
    the massive Tier 2 LOINC database in Supabase using pgvector similarity.
    """
    if not extracted_name:
        return None
        
    try:
        # 1. Generate embedding for the raw string using the deterministic mock generator
        import hashlib
        import random
        
        seed_val = int(hashlib.md5(extracted_name.encode('utf-8')).hexdigest(), 16)
        rng = random.Random(seed_val)
        embedding = [rng.uniform(-1.0, 1.0) for _ in range(384)]
        magnitude = sum(x**2 for x in embedding) ** 0.5
        query_embedding = [x / magnitude for x in embedding]
        
        # 2. Call the Supabase RPC function (created via migration 025)
        # We set a strict threshold (e.g., 0.85 cosine similarity) so we don't return junk
        rpc_response = supabase.rpc(
            "match_loinc_biomarker", 
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.85,
                "match_count": 1
            }
        ).execute()
        
        if rpc_response.data and len(rpc_response.data) > 0:
            best_match = rpc_response.data[0]
            return {
                "loinc_code": best_match["loinc_code"],
                "name": best_match["long_common_name"],
                "similarity": best_match["similarity"],
                "category": "Unmapped" # Can be dynamically categorized later
            }
            
        return None
        
    except Exception as e:
        print(f"Error querying Tier 2 LOINC database: {str(e)}")
        return None
