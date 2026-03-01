import json
import dataclasses
from Platform.Kalshi import KalshiClient


def to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def main():
    client = KalshiClient()

    print("Fetching open events (closing within 30 days)...")
    events = client.fetch_all_events(status="open", within_days=30)
    print(f"  -> {len(events)} events fetched")

    with open("kalshi_events.json", "w", encoding="utf-8") as f:
        json.dump([to_dict(e) for e in events], f, indent=2, ensure_ascii=False)
    print("  -> saved to kalshi_events.json")


if __name__ == "__main__":
    main()
