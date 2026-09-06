import httpx, os, json
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv('USDA_API_KEY')
url = f'https://api.nal.usda.gov/fdc/v1/foods/search?query=%22raw green beans%22&api_key={api_key}&pageSize=5'
res = httpx.get(url).json()
for f in res.get('foods', []): print(f['description'], f['dataType'])
