import httpx
import asyncio
from app.config import settings
async def test():
    resp = await httpx.AsyncClient().get(f'https://api.nal.usda.gov/fdc/v1/foods/search?query=chicken&api_key={settings.USDA_API_KEY}&pageSize=5')
    data = resp.json()
    for food in data.get('foods', []):
        for n in food.get('foodNutrients', []):
            if n.get('value') is None:
                print("FOUND NONE VALUE for", n.get('nutrientName'))
if __name__ == "__main__":
    asyncio.run(test())
