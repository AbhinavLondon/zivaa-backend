import asyncio
import httpx
import os
import base64

async def main():
    url = "http://127.0.0.1:8000/api/v1/nutrition/analyze-meal-photo"
    
    print("Testing photo analysis...")
    img_data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    with open("test.png", "wb") as f:
        f.write(img_data)
        
    async with httpx.AsyncClient() as client:
        try:
            with open("test.png", "rb") as f:
                files = {"file": ("test.png", f, "image/png")}
                resp = await client.post(url, files=files, timeout=60)
                print("Status:", resp.status_code)
                print("Response:", resp.text)
        except Exception as e:
            print(f"Error calling backend: {e}")

if __name__ == "__main__":
    asyncio.run(main())
