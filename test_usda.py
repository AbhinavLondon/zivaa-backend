import asyncio
from app.api.endpoints.nutrition import resolve_foods_via_usda
from pydantic import BaseModel
class Food(BaseModel):
    name: str
    quantity_g: float
    fallback_calories: int
    fallback_protein_g: float
    fallback_carbs_g: float
    fallback_fat_g: float
async def test():
    f = Food(name='diet coke', quantity_g=330, fallback_calories=0, fallback_protein_g=0, fallback_carbs_g=0, fallback_fat_g=0)
    res = await resolve_foods_via_usda([f.dict()])
    print(res)
asyncio.run(test())
