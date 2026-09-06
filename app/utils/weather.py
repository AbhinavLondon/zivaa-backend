import httpx

def get_city_temperature(city: str) -> float | None:
    """
    Fetches the current temperature (in Celsius) for a given city 
    using the wttr.in public API. Returns None if it fails.
    """
    if not city:
        return None
        
    try:
        wttr_res = httpx.get(f"https://wttr.in/{city}?format=j1", timeout=3.0)
        if wttr_res.status_code == 200:
            return float(wttr_res.json()["current_condition"][0]["temp_C"])
    except Exception as e:
        print(f"Warning: Could not fetch temperature for {city}: {e}")
        
    return None
