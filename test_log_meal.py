import httpx
import asyncio

async def test():
    payload = {
        "patient_id": "33333333-3333-3333-3333-333333333333",
        "meal_type": "lunch",
        "logging_method": "photo",
        "ai_analysis": "Great meal!",
        "foods": [
            {"name":"raw lentils (80.0g)","calories":281.6,"protein_g":19.68,"carbs_g":50.72,"fat_g":0.85,"sodium_mg":4.8,"potassium_mg":541.6,"fiber_g":8.56,"calcium_mg":28.0,"vitamin_k_mcg":4.0}
        ]
    }
    resp = await httpx.AsyncClient().post('http://127.0.0.1:8000/api/v1/nutrition/log-meal', json=payload)
    print("Log meal status:", resp.status_code)
    print("Log meal response:", resp.text)

if __name__ == "__main__":
    asyncio.run(test())
