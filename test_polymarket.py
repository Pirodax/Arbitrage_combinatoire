import json
import dataclasses
from Platform.Polymarket import PolymarketClient


def to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def main():
    client = PolymarketClient()

    print("Fetching active events (closing within 30 days)...")
    events = client.fetch_all_events(active=True, closed=False, within_days=30)
    print(f"  -> {len(events)} events fetched")

    with open("polymarket_events.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(e) for e in events], f, indent=2, ensure_ascii=False)
    print("  -> saved to polymarket_events.json")

    print("Fetching active markets (closing within 30 days)...")
    markets = client.fetch_all_markets(active=True, closed=False, within_days=30)
    print(f"  -> {len(markets)} markets fetched")

    with open("polymarket_markets.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(m) for m in markets], f, indent=2, ensure_ascii=False)
    print("  -> saved to polymarket_markets.json")


if __name__ == "__main__":
    main()
