"""Test script for vitals cards API endpoint with timeframe parameters."""
import sys, os
# Add user-site packages to sys.path so IDE linter resolves imports
user_site = os.path.expanduser("~\\AppData\\Roaming\\Python\\Python314\\site-packages")
if user_site not in sys.path and os.path.exists(user_site):
    sys.path.insert(0, user_site)

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_vitals_cards_endpoint(pid: str, name: str, timeframe: str):
    print("=" * 70)
    print(f"API CALL FOR {name.upper()}'S VITALS CARDS (Timeframe: {timeframe})")
    print("=" * 70)
    
    response = client.get(f"/api/v1/health/vitals-cards/{pid}?timeframe={timeframe}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
    
    data = response.json()
    assert "cards" in data, "Response body should contain 'cards' key"
    
    cards = data["cards"]
    print(f"Received {len(cards)} vitals cards:")
    for card in cards:
        print(f"- [{card['title']}] ({card['metric_id']})")
        print(f"  Display Value: {card['display_value']} {card['unit']} ({card['label']})")
        print(f"  Insight: {card['insight']}")
        print(f"  Trend data points: {len(card['trend_bars'])}")
    print()

def main():
    # Neha - Today
    test_vitals_cards_endpoint("22222222-2222-2222-2222-222222222222", "Neha", "Today")
    # Neha - 30 Days
    test_vitals_cards_endpoint("22222222-2222-2222-2222-222222222222", "Neha", "30 Days")

if __name__ == "__main__":
    main()
    print("All vitals cards API endpoint tests passed!")
