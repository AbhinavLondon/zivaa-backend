import httpx, os, json
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv('USDA_API_KEY')
url = f'https://api.nal.usda.gov/fdc/v1/foods/search?query=diet coke&api_key={api_key}&pageSize=1'
print(json.dumps(httpx.get(url).json(), indent=2))
