"""Test script for vitals cards service with timeframes."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.vitals_cards import generate_vitals_cards

async def test_cards_with_timeframe(pid: str, name: str, timeframe: str):
    print("=" * 65)
    print(f"VITALS CARDS FOR {name.upper()} - TIMEFRAME: {timeframe.upper()}")
    print("=" * 65)
    
    cards = await generate_vitals_cards(pid, timeframe)
    for card in cards:
        print(f"[{card['title']}] ({card['metric_id']})")
        print(f"  Display value: {card['display_value']} {card['unit']} ({card['label']})")
        print(f"  Insight: {card['insight']}")
        print(f"  Trend bars count: {len(card['trend_bars'])}")
        # Print first and last values for preview
        if card['trend_bars']:
            first = card['trend_bars'][0]
            last = card['trend_bars'][-1]
            first_dia = f"/{int(first['diastolic'])}" if 'diastolic' in first else ""
            last_dia = f"/{int(last['diastolic'])}" if 'diastolic' in last else ""
            print(f"  Trend preview: First on {first['date']} ({first['value']}{first_dia}, {first['status']}) "
                  f"-> Last on {last['date']} ({last['value']}{last_dia}, {last['status']})")
        print("-" * 40)
    print()

async def main():
    # Neha
    await test_cards_with_timeframe("22222222-2222-2222-2222-222222222222", "Neha", "Today")
    await test_cards_with_timeframe("22222222-2222-2222-2222-222222222222", "Neha", "7 days")
    await test_cards_with_timeframe("22222222-2222-2222-2222-222222222222", "Neha", "30 Days")
    await test_cards_with_timeframe("22222222-2222-2222-2222-222222222222", "Neha", "3 Months")

if __name__ == "__main__":
    asyncio.run(main())
