import httpx
import asyncio
from app.config import settings

async def test():
    key = settings.USDA_API_KEY
    print(f"Current key: {key}")
    resp = await httpx.AsyncClient().get(f'https://api.nal.usda.gov/fdc/v1/foods/search?query=apple&api_key={key}&pageSize=1')
    print("USDA status:", resp.status_code)

if __name__ == "__main__":
    asyncio.run(test())
