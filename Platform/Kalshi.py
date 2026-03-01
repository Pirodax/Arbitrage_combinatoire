import requests
from dataclasses import dataclass, field
from typing import Optional


KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass
class KalshiMarket:
    ticker: str
    event_ticker: str
    title: str
    market_type: str
    status: str
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    last_price: Optional[float]
    volume: int
    volume_24h: int
    open_interest: int
    close_time: Optional[str]
    yes_sub_title: str
    no_sub_title: str

    @classmethod
    def from_dict(cls, data: dict) -> "KalshiMarket":
        return cls(
            ticker=data.get("ticker", ""),
            event_ticker=data.get("event_ticker", ""),
            title=data.get("title", ""),
            market_type=data.get("market_type", "binary"),
            status=data.get("status", ""),
            yes_bid=float(data["yes_bid"]) / 100 if data.get("yes_bid") is not None else None,
            yes_ask=float(data["yes_ask"]) / 100 if data.get("yes_ask") is not None else None,
            no_bid=float(data["no_bid"]) / 100 if data.get("no_bid") is not None else None,
            no_ask=float(data["no_ask"]) / 100 if data.get("no_ask") is not None else None,
            last_price=float(data["last_price"]) / 100 if data.get("last_price") is not None else None,
            volume=data.get("volume", 0),
            volume_24h=data.get("volume_24h", 0),
            open_interest=data.get("open_interest", 0),
            close_time=data.get("close_time"),
            yes_sub_title=data.get("yes_sub_title", ""),
            no_sub_title=data.get("no_sub_title", ""),
        )


@dataclass
class KalshiEvent:
    event_ticker: str
    series_ticker: str
    title: str
    sub_title: str
    category: str
    status: str
    last_updated_ts: str
    markets: list[KalshiMarket] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "KalshiEvent":
        markets = [KalshiMarket.from_dict(m) for m in data.get("markets", [])]
        return cls(
            event_ticker=data.get("event_ticker", ""),
            series_ticker=data.get("series_ticker", ""),
            title=data.get("title", ""),
            sub_title=data.get("sub_title", ""),
            category=data.get("category", ""),
            status=data.get("status", ""),
            last_updated_ts=data.get("last_updated_ts", ""),
            markets=markets,
        )


class KalshiClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict) -> dict:
        url = f"{KALSHI_API_BASE}{path}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def fetch_events(
        self,
        status: str = "open",
        with_nested_markets: bool = True,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> tuple[list[KalshiEvent], Optional[str]]:
        params: dict = {
            "limit": limit,
            "status": status,
            "with_nested_markets": str(with_nested_markets).lower(),
        }
        if cursor:
            params["cursor"] = cursor

        data = self._get("/events", params)
        events = [KalshiEvent.from_dict(e) for e in data.get("events", [])]
        next_cursor = data.get("cursor") or None
        return events, next_cursor

    def fetch_all_events(self, status: str = "open") -> list[KalshiEvent]:
        events: list[KalshiEvent] = []
        cursor = None
        while True:
            batch, cursor = self.fetch_events(status=status, cursor=cursor)
            events.extend(batch)
            if not cursor:
                break
        return events

    def fetch_markets(
        self,
        status: str = "open",
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> tuple[list[KalshiMarket], Optional[str]]:
        params: dict = {"limit": limit, "status": status}
        if cursor:
            params["cursor"] = cursor

        data = self._get("/markets", params)
        markets = [KalshiMarket.from_dict(m) for m in data.get("markets", [])]
        next_cursor = data.get("cursor") or None
        return markets, next_cursor

    def fetch_all_markets(self, status: str = "open") -> list[KalshiMarket]:
        markets: list[KalshiMarket] = []
        cursor = None
        while True:
            batch, cursor = self.fetch_markets(status=status, cursor=cursor)
            markets.extend(batch)
            if not cursor:
                break
        return markets
