import json
import dataclasses
from Platform.Kalshi import KalshiClient


def to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def main():
    client = KalshiClient()

    print("Fetching open events...")
    events, _ = client.fetch_events(status="open", limit=10)
    print(f"  -> {len(events)} events fetched")

    with open("kalshi_events.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(e) for e in events], f, indent=2, ensure_ascii=False)
    print("  -> saved to kalshi_events.json")

    print("Fetching open markets...")
    markets, _ = client.fetch_markets(status="open", limit=10)
    print(f"  -> {len(markets)} markets fetched")

    with open("kalshi_markets.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(m) for m in markets], f, indent=2, ensure_ascii=False)
    print("  -> saved to kalshi_markets.json")


if __name__ == "__main__":
    main()
