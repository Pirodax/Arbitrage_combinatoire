"""
Match identical markets across Polymarket and Kalshi using
fuzzy text similarity + date proximity scoring + category filter + entity overlap.

Unit matched: individual markets (not events).
  - Polymarket market: "question" field
  - Kalshi    market: "title"    field

Arbitrage logic:
  - YES_PM + NO_KS  → profit = 1 - (pm_yes_ask + ks_no_ask)
  - NO_PM  + YES_KS → profit = 1 - (pm_no_ask  + ks_yes_ask)
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from rapidfuzz import fuzz


# ── weights & thresholds ──────────────────────────────────────────────────────
W_TEXT          = 0.90
W_DATE          = 0.10
SCORE_THRESHOLD = 65.0
DATE_DECAY_DAYS = 365
WITHIN_DAYS     = 30


# ── category mapping ──────────────────────────────────────────────────────────
# Polymarket tag → catégorie normalisée
_PM_TAG_TO_CAT: dict[str, str] = {
    "Sports": "sports", "Games": "sports", "Soccer": "sports",
    "Basketball": "sports", "NCAA": "sports", "NCAA Basketball": "sports",
    "Hockey": "sports", "Esports": "sports", "MMA": "sports",
    "Ligue 1": "sports", "NFL": "sports", "NBA": "sports",
    "Crypto": "crypto", "Crypto Prices": "crypto",
    "Bitcoin": "crypto", "Ethereum": "crypto", "XRP": "crypto",
    "Solana": "crypto", "Ripple": "crypto",
    "Politics": "politics", "US Elections": "politics",
    "Elections": "politics", "Geopolitics": "politics",
    "World": "world",
    "Weather": "weather", "Daily Temperature": "weather",
    "Culture": "entertainment", "Entertainment": "entertainment",
    "Economics": "economics", "Finance": "economics",
    "Companies": "companies",
}

# Kalshi category → catégorie normalisée
_KS_CAT_TO_CAT: dict[str, str] = {
    "Sports": "sports",
    "Elections": "politics",
    "Politics": "politics",
    "Entertainment": "entertainment",
    "Economics": "economics",
    "Climate and Weather": "weather",
    "Crypto": "crypto",
    "Companies": "companies",
    "Financials": "economics",
    "World": "world",
    "Science and Technology": "other",
    "Health": "other",
    "Transportation": "other",
    "Social": "other",
    "Mentions": "other",
}

def _pm_category(event: dict) -> str:
    """Retourne la catégorie normalisée d'un event Polymarket depuis ses tags."""
    for tag in event.get("tags", []):
        cat = _PM_TAG_TO_CAT.get(tag)
        if cat:
            return cat
    return "other"

def _ks_category(event: dict) -> str:
    """Retourne la catégorie normalisée d'un event Kalshi."""
    raw = event.get("category", "") or ""
    return _KS_CAT_TO_CAT.get(raw, "other")


# ── entity extraction ─────────────────────────────────────────────────────────
# Extrait les tokens "clés" d'un titre : nombres + mots capitalisés (entités nommées)
_ENTITY_SKIP = {"Will", "Who", "What", "When", "How", "Is", "Are", "Does",
                "Be", "The", "A", "An", "In", "On", "At", "By", "To",
                "Of", "Or", "And", "For", "Mar", "Feb", "Jan", "Apr",
                "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"}

def entity_tokens(text: str) -> set[str]:
    """Retourne les entités nommées + nombres d'un texte."""
    text = re.sub(r"\*+", "", text)
    tokens: set[str] = set()
    # nombres (prix, températures, scores)
    for n in re.findall(r"\d+(?:[.,]\d+)?", text):
        tokens.add(n.replace(",", ""))
    # mots capitalisés (villes, noms propres, actifs)
    for w in re.findall(r"\b[A-Z][a-z]{2,}\b", text):
        if w not in _ENTITY_SKIP:
            tokens.add(w.lower())
    return tokens

def entities_compatible(pm_q: str, ks_t: str) -> bool:
    """
    Retourne True si les entités sont compatibles :
    - soit l'une des deux n'a pas d'entités (pas de contrainte)
    - soit il y a au moins 1 entité commune
    """
    pm_e = entity_tokens(pm_q)
    ks_e = entity_tokens(ks_t)
    if not pm_e or not ks_e:
        return True
    return bool(pm_e & ks_e)


# ── text helpers ───────────────────────────────────────────────────────────────
_STOP = {"will", "the", "a", "an", "in", "on", "at", "by", "to", "of",
         "be", "is", "any", "or", "and", "for", "before", "after",
         "this", "that", "with", "from"}

def normalize(text: str) -> str:
    text = re.sub(r"\*+", "", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(t for t in text.split() if t not in _STOP)

def text_score(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(normalize(a), normalize(b))


# ── date helpers ──────────────────────────────────────────────────────────────
def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None

def date_score(d1: Optional[str], d2: Optional[str]) -> float:
    dt1, dt2 = parse_date(d1), parse_date(d2)
    if dt1 is None or dt2 is None:
        return 50.0
    delta = abs((dt1 - dt2).days)
    return round(100.0 * (0.05 ** (delta / DATE_DECAY_DAYS)), 2)

def final_score(ts: float, ds: float) -> float:
    return round(W_TEXT * ts + W_DATE * ds, 2)


# ── flatten events → markets ──────────────────────────────────────────────────
_PM_EXCLUDE = re.compile(r"\bup or down\b|\bup/down\b|\b\d+:\d+\s*[ap]m\b", re.IGNORECASE)

def flatten_pm_markets(events: list[dict]) -> list[dict]:
    """Extrait les markets Polymarket binaires avec leur catégorie normalisée."""
    markets = []
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=WITHIN_DAYS)
    for event in events:
        cat = _pm_category(event)
        for m in event.get("markets", []):
            question = m.get("question", "")
            if _PM_EXCLUDE.search(question):
                continue
            end = m.get("end_date") or event.get("end_date")
            dt = parse_date(end)
            if dt and now <= dt <= cutoff:
                m["_end_date"] = end
                m["_category"] = cat
                markets.append(m)
    return markets

def flatten_ks_markets(events: list[dict]) -> list[dict]:
    """Extrait les markets Kalshi binaires avec leur catégorie normalisée."""
    markets = []
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=WITHIN_DAYS)
    for event in events:
        event_markets = event.get("markets", [])
        titles = [m.get("title", "") for m in event_markets]
        if len(set(titles)) < len(titles):   # brackets scalaires → exclure
            continue
        cat = _ks_category(event)
        for m in event_markets:
            end = m.get("close_time")
            dt = parse_date(end)
            if dt and now <= dt <= cutoff:
                m["_end_date"] = end
                m["_category"] = cat
                markets.append(m)
    return markets


# ── data loading ──────────────────────────────────────────────────────────────
def load_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── match result ──────────────────────────────────────────────────────────────
@dataclass
class Match:
    pm_question: str
    pm_end:      Optional[str]
    pm_category: str
    pm_yes_ask:  Optional[float]
    pm_no_ask:   Optional[float]
    ks_title:    str
    ks_end:      Optional[str]
    ks_category: str
    ks_yes_ask:  Optional[float]
    ks_no_ask:   Optional[float]
    text_score:  float
    date_score:  float
    score:       float

    def arb_yes_pm_no_ks(self) -> Optional[float]:
        if self.pm_yes_ask is not None and self.ks_no_ask is not None:
            return round(1 - (self.pm_yes_ask + self.ks_no_ask), 4)
        return None

    def arb_no_pm_yes_ks(self) -> Optional[float]:
        if self.pm_no_ask is not None and self.ks_yes_ask is not None:
            return round(1 - (self.pm_no_ask + self.ks_yes_ask), 4)
        return None

    def best_arb(self) -> Optional[float]:
        candidates = [x for x in [self.arb_yes_pm_no_ks(), self.arb_no_pm_yes_ks()] if x is not None]
        return max(candidates) if candidates else None

    def best_arb_direction(self) -> Optional[str]:
        a, b = self.arb_yes_pm_no_ks(), self.arb_no_pm_yes_ks()
        if a is None and b is None:
            return None
        if a is None: return "NO_PM + YES_KS"
        if b is None: return "YES_PM + NO_KS"
        return "YES_PM + NO_KS" if a >= b else "NO_PM + YES_KS"


# ── matching logic ────────────────────────────────────────────────────────────
def match(pm_markets: list[dict], ks_markets: list[dict]) -> list[Match]:
    results: list[Match] = []

    for pm in pm_markets:
        pm_question = pm.get("question", "")
        pm_end      = pm.get("_end_date")
        pm_cat      = pm.get("_category", "other")
        pm_yes_ask  = pm.get("best_ask")
        pm_yes_bid  = pm.get("best_bid")
        pm_no_ask   = round(1 - pm_yes_bid, 4) if pm_yes_bid is not None else None

        best: Optional[Match] = None

        for ks in ks_markets:
            ks_cat = ks.get("_category", "other")

            # ── filtre 1 : catégorie incompatible ─────────────────────────────
            if pm_cat != ks_cat and "other" not in (pm_cat, ks_cat):
                continue

            ks_title   = ks.get("title", "")

            # ── filtre 2 : entités nommées incompatibles ──────────────────────
            if not entities_compatible(pm_question, ks_title):
                continue

            ks_end     = ks.get("_end_date")
            ks_yes_ask = ks.get("yes_ask")
            ks_no_ask  = ks.get("no_ask")

            ts = text_score(pm_question, ks_title)
            ds = date_score(pm_end, ks_end)
            fs = final_score(ts, ds)

            if fs < SCORE_THRESHOLD:
                continue

            candidate = Match(
                pm_question=pm_question, pm_end=pm_end, pm_category=pm_cat,
                pm_yes_ask=pm_yes_ask, pm_no_ask=pm_no_ask,
                ks_title=ks_title, ks_end=ks_end, ks_category=ks_cat,
                ks_yes_ask=ks_yes_ask, ks_no_ask=ks_no_ask,
                text_score=ts, date_score=ds, score=fs,
            )
            if best is None or fs > best.score:
                best = candidate

        if best:
            results.append(best)

    results.sort(key=lambda m: (m.best_arb() or -999), reverse=True)
    return results


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    pm_events = load_json("polymarket_events.json")
    ks_events = load_json("kalshi_events.json")

    pm_markets = flatten_pm_markets(pm_events)
    ks_markets = flatten_ks_markets(ks_events)

    print(f"Polymarket markets (≤{WITHIN_DAYS}j) : {len(pm_markets)}")
    print(f"Kalshi    markets (≤{WITHIN_DAYS}j) : {len(ks_markets)}")
    print(f"Threshold                         : {SCORE_THRESHOLD}/100\n")

    matches = match(pm_markets, ks_markets)
    print(f"Matches trouvés : {len(matches)}\n")

    output = []
    for m in matches:
        arb = m.best_arb()
        flag = " ⚡ ARB" if arb is not None and arb > 0 else ""
        print(f"[{m.score:5.1f}] [{m.pm_category}]{flag}")
        print(f"  PM : {m.pm_question[:65]}  (fin: {m.pm_end[:10] if m.pm_end else '?'})")
        print(f"  KS : {m.ks_title[:65]}")
        print(f"  PM yes_ask={m.pm_yes_ask}  no_ask={m.pm_no_ask}")
        print(f"  KS yes_ask={m.ks_yes_ask}  no_ask={m.ks_no_ask}")
        print(f"  → {m.best_arb_direction()}  profit={arb}\n")

        output.append({
            "match_score": m.score,
            "text_score":  m.text_score,
            "date_score":  m.date_score,
            "category":    m.pm_category,
            "arbitrage": {
                "best_profit": arb,
                "direction":   m.best_arb_direction(),
                "yes_pm_no_ks":  m.arb_yes_pm_no_ks(),
                "no_pm_yes_ks":  m.arb_no_pm_yes_ks(),
            },
            "polymarket": {"question": m.pm_question, "end": m.pm_end,
                           "yes_ask": m.pm_yes_ask, "no_ask": m.pm_no_ask},
            "kalshi":     {"title": m.ks_title, "end": m.ks_end,
                           "yes_ask": m.ks_yes_ask, "no_ask": m.ks_no_ask},
        })

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"→ saved to matches.json")


if __name__ == "__main__":
    main()
