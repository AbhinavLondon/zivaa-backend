import httpx
import asyncio

async def test():
    print("Testing /log-meal...")
    payload = {
        "patient_id": "33333333-3333-3333-3333-333333333333",
        "meal_type": "lunch",
        "meal_name": "Test Rajma Chawal",
        "logging_method": "photo",
        "ai_analysis": "Great meal!",
        "foods": [
            {
                "name": "raw lentils (100.0g)",
                "calories": 200,
                "protein_g": 10,
                "carbs_g": 20,
                "fat_g": 1,
                "sodium_mg": 0,
                "potassium_mg": 0,
                "fiber_g": 0,
                "calcium_mg": 0,
                "vitamin_k_mcg": 0
            }
        ]
    }
    
    # Pre-populate cache so we can see if it picks it up
    # Wait, the cache is internal to the Uvicorn process.
    # So if we hit /log-meal directly, it will just use 0 for micros (which is fine, we are testing the unified row insertion)
    
    async with httpx.AsyncClient() as client:
        log_resp = await client.post("http://127.0.0.1:8000/api/v1/nutrition/log-meal", json=payload)
        print("Log meal status:", log_resp.status_code)
        print("Log meal response:", log_resp.text)

if __name__ == "__main__":
    asyncio.run(test())
