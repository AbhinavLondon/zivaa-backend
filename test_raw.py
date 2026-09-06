import httpx
import asyncio
from app.config import settings
async def test():
    resp = await httpx.AsyncClient().get(f'https://api.nal.usda.gov/fdc/v1/foods/search?query=raw%20lentils&api_key={settings.USDA_API_KEY}&pageSize=1')
    print(len(resp.json().get('foods', [])))
if __name__ == "__main__":
    asyncio.run(test())
