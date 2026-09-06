import asyncio
import json
import httpx

async def main():
    url_text = "http://127.0.0.1:8000/api/v1/nutrition/analyze-meal-text"
    print("Testing text analysis...")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url_text, json={"text": "A bowl of lentils"}, timeout=30)
            print("Status:", resp.status_code)
            print("Response:", resp.text)
        except Exception as e:
            print(f"Error calling backend: {e}")

if __name__ == "__main__":
    asyncio.run(main())
