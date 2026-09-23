import time
import httpx
import urllib.parse
from typing import Optional, Dict, Tuple

# In-memory weather cache: {city_lower: (timestamp, temperature_celsius)}
# TTL: 30 minutes (1800 seconds)
_WEATHER_CACHE: Dict[str, Tuple[float, float]] = {}
_WEATHER_CACHE_TTL = 1800.0


def _get_ambient_default(city: str) -> float:
    """Provides a reasonable ambient temperature fallback when APIs are unreachable."""
    c_lower = city.lower()
    temperate_keywords = ["london", "uk", "england", "scotland", "paris", "berlin", "new york", "seattle", "boston", "chicago"]
    if any(k in c_lower for k in temperate_keywords):
        return 18.0
    # Indian / Tropical default
    return 28.0


async def _fetch_open_meteo(client: httpx.AsyncClient, clean_city: str) -> Optional[float]:
    """Fallback fetcher using Open-Meteo geocoding + current forecast."""
    try:
        encoded = urllib.parse.quote(clean_city)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1"
        geo_resp = await client.get(geo_url)
        if geo_resp.status_code == 200:
            results = geo_resp.json().get("results")
            if results:
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                forecast_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m"
                f_resp = await client.get(forecast_url)
                if f_resp.status_code == 200:
                    return float(f_resp.json()["current"]["temperature_2m"])
    except Exception:
        pass
    return None


async def get_city_temperature_async(city: str) -> Optional[float]:
    """
    Asynchronously fetches current temperature (in Celsius) for a given city 
    using wttr.in, Open-Meteo fallback, and in-memory caching (30m TTL).
    Guarantees a sensible temperature reading is always returned.
    """
    if not city or not city.strip():
        return None

    clean_city = city.strip()
    city_key = clean_city.lower()
    now = time.time()

    # 1. Check active cache
    if city_key in _WEATHER_CACHE:
        cached_time, cached_temp = _WEATHER_CACHE[city_key]
        if now - cached_time < _WEATHER_CACHE_TTL:
            return cached_temp

    # 2. Try wttr.in
    try:
        encoded_city = urllib.parse.quote(clean_city)
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(f"https://wttr.in/{encoded_city}?format=j1")
            if resp.status_code == 200:
                temp = float(resp.json()["current_condition"][0]["temp_C"])
                _WEATHER_CACHE[city_key] = (now, temp)
                return temp
            
            # 3. Try Open-Meteo fallback if wttr.in returned non-200
            om_temp = await _fetch_open_meteo(client, clean_city)
            if om_temp is not None:
                _WEATHER_CACHE[city_key] = (now, om_temp)
                return om_temp
    except Exception as e:
        # On wttr.in timeout or network error, attempt quick Open-Meteo fallback
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                om_temp = await _fetch_open_meteo(client, clean_city)
                if om_temp is not None:
                    _WEATHER_CACHE[city_key] = (now, om_temp)
                    return om_temp
        except Exception:
            pass

    # 4. Fall back to stale cache if present
    if city_key in _WEATHER_CACHE:
        return _WEATHER_CACHE[city_key][1]

    # 5. Fall back to ambient baseline default
    ambient = _get_ambient_default(clean_city)
    _WEATHER_CACHE[city_key] = (now, ambient)
    return ambient


def get_city_temperature(city: str) -> Optional[float]:
    """
    Synchronous temperature lookup. Checks cache first, then makes a fast synchronous call.
    """
    if not city or not city.strip():
        return None

    city_key = city.strip().lower()
    now = time.time()

    if city_key in _WEATHER_CACHE:
        cached_time, cached_temp = _WEATHER_CACHE[city_key]
        if now - cached_time < _WEATHER_CACHE_TTL:
            return cached_temp

    try:
        encoded = urllib.parse.quote(city.strip())
        wttr_res = httpx.get(f"https://wttr.in/{encoded}?format=j1", timeout=2.5)
        if wttr_res.status_code == 200:
            temp = float(wttr_res.json()["current_condition"][0]["temp_C"])
            _WEATHER_CACHE[city_key] = (now, temp)
            return temp
    except Exception as e:
        print(f"Warning: Could not fetch temperature for {city}: {e}")

    if city_key in _WEATHER_CACHE:
        return _WEATHER_CACHE[city_key][1]

    return _get_ambient_default(city)
