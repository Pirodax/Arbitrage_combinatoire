import json
import dataclasses
from Platform.Polymarket import PolymarketClient


def to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def main():
    client = PolymarketClient()

    print("Fetching active events...")
    events = client.fetch_events(active=True, closed=False, limit=10)
    print(f"  -> {len(events)} events fetched")

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(e) for e in events], f, indent=2, ensure_ascii=False)
    print("  -> saved to events.json")

    print("Fetching active markets...")
    markets = client.fetch_markets(active=True, closed=False, limit=10)
    print(f"  -> {len(markets)} markets fetched")

    with open("markets.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(m) for m in markets], f, indent=2, ensure_ascii=False)
    print("  -> saved to markets.json")


if __name__ == "__main__":
    main()
