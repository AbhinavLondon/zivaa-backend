import asyncio
import httpx

async def main():
    url = "http://127.0.0.1:8000/api/v1/nutrition/analyze-barcode"
    payload = {"barcode": "5449000000996"}
    
    print("Testing barcode analysis...")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, timeout=30)
            print("Status:", resp.status_code)
            print("Response:", resp.text)
        except Exception as e:
            print(f"Error calling backend: {e}")

if __name__ == "__main__":
    asyncio.run(main())
