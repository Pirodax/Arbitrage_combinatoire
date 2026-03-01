import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


GAMMA_API_BASE = "https://gamma-api.polymarket.com"


@dataclass
class Market:
    id: str
    condition_id: str
    question: str
    slug: str
    category: str
    market_type: str
    outcomes: list[str]
    outcome_prices: list[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    last_trade_price: Optional[float]
    liquidity: float
    volume: float
    volume_24hr: float
    active: bool
    closed: bool
    start_date: Optional[str]
    end_date: Optional[str]
    clob_token_ids: list[str] = field(default_factory=list)

    @property
    def yes_ask(self) -> Optional[float]:
        """Prix d'achat du YES (best_ask)."""
        return self.best_ask

    @property
    def no_ask(self) -> Optional[float]:
        """Prix d'achat du NO ≈ 1 - yes_bid."""
        return round(1 - self.best_bid, 4) if self.best_bid is not None else None

    @classmethod
    def from_dict(cls, data: dict) -> "Market":
        outcomes_raw = data.get("outcomes", "[]")
        if isinstance(outcomes_raw, str):
            import json
            outcomes = json.loads(outcomes_raw)
        else:
            outcomes = outcomes_raw

        prices_raw = data.get("outcomePrices", "[]")
        if isinstance(prices_raw, str):
            import json
            prices = [float(p) for p in json.loads(prices_raw)]
        else:
            prices = [float(p) for p in prices_raw]

        clob_raw = data.get("clobTokenIds", "[]")
        if isinstance(clob_raw, str):
            import json
            clob_ids = json.loads(clob_raw)
        else:
            clob_ids = clob_raw or []

        return cls(
            id=data.get("id", ""),
            condition_id=data.get("conditionId", ""),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            category=data.get("category", ""),
            market_type=data.get("marketType", "normal"),
            outcomes=outcomes,
            outcome_prices=prices,
            best_bid=float(data["bestBid"]) if data.get("bestBid") else None,
            best_ask=float(data["bestAsk"]) if data.get("bestAsk") else None,
            last_trade_price=float(data["lastTradePrice"]) if data.get("lastTradePrice") else None,
            liquidity=float(data.get("liquidityNum") or data.get("liquidity") or 0),
            volume=float(data.get("volumeNum") or data.get("volume") or 0),
            volume_24hr=float(data.get("volume24hr") or 0),
            active=data.get("active", False),
            closed=data.get("closed", False),
            start_date=data.get("startDate"),
            end_date=data.get("endDate"),
            clob_token_ids=clob_ids,
        )


@dataclass
class Event:
    id: str
    ticker: str
    slug: str
    title: str
    description: str
    tags: list[str]
    active: bool
    closed: bool
    liquidity: float
    volume: float
    volume_24hr: float
    start_date: Optional[str]
    end_date: Optional[str]
    markets: list[Market] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        markets = [Market.from_dict(m) for m in data.get("markets", [])]
        tags = [t["label"] for t in data.get("tags", []) if "label" in t]
        return cls(
            id=data.get("id", ""),
            ticker=data.get("ticker", ""),
            slug=data.get("slug", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            tags=tags,
            active=data.get("active", False),
            closed=data.get("closed", False),
            liquidity=float(data.get("liquidity") or 0),
            volume=float(data.get("volume") or 0),
            volume_24hr=float(data.get("volume24hr") or 0),
            start_date=data.get("startDate"),
            end_date=data.get("endDate"),
            markets=markets,
        )


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class PolymarketClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict) -> list[dict]:
        url = f"{GAMMA_API_BASE}{path}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def fetch_events(
        self,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Event]:
        params: dict = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()

        data = self._get("/events", params)
        return [Event.from_dict(item) for item in data]

    def fetch_all_events(
        self,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        within_days: Optional[int] = None,
    ) -> list[Event]:
        cutoff = datetime.now(timezone.utc) + timedelta(days=within_days) if within_days else None
        events: list[Event] = []
        offset = 0
        limit = 100
        while True:
            # la pagination se base sur le nombre brut retourné par l'API
            batch = self.fetch_events(active=active, closed=closed, limit=limit, offset=offset)
            raw_count = len(batch)
            if cutoff is not None:
                batch = [
                    e for e in batch
                    if e.end_date and _parse_dt(e.end_date) is not None
                    and _parse_dt(e.end_date) <= cutoff
                ]
            events.extend(batch)
            if raw_count < limit:
                break
            offset += limit
        return events

    def fetch_markets(
        self,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Market]:
        params: dict = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()

        data = self._get("/markets", params)
        return [Market.from_dict(item) for item in data]

    def fetch_all_markets(
        self,
        active: Optional[bool] = None,
        closed: Optional[bool] = None,
        within_days: Optional[int] = None,
    ) -> list[Market]:
        cutoff = datetime.now(timezone.utc) + timedelta(days=within_days) if within_days else None
        markets: list[Market] = []
        offset = 0
        limit = 100
        while True:
            batch = self.fetch_markets(active=active, closed=closed, limit=limit, offset=offset)
            raw_count = len(batch)
            if cutoff is not None:
                batch = [
                    m for m in batch
                    if m.end_date and _parse_dt(m.end_date) is not None
                    and _parse_dt(m.end_date) <= cutoff
                ]
            markets.extend(batch)
            if raw_count < limit:
                break
            offset += limit
        return markets
