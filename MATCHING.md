# Matching de marchés cross-plateforme

## Objectif

Identifier automatiquement les marchés **identiques ou équivalents** entre Polymarket et Kalshi afin de détecter des opportunités d'arbitrage (différence de prix sur le même événement).

---

## Pipeline

```
polymarket_events.json          kalshi_events.json
        │                               │
        └──────────────┬────────────────┘
                       ▼
           flatten_pm_markets / flatten_ks_markets
           (filtre ≤ WITHIN_DAYS, exclut scalaires)
                       │
                       ▼
              Filtre 1 : catégorie identique
                       │
              Filtre 2 : entités nommées compatibles
                       │
              Filtre 3 : score final ≥ SCORE_THRESHOLD
                       │
              Filtre 4 : validation sémantique dure
                       │
                       ▼
                 matches.json
```

---

## 1. Normalisation du titre

Avant tout calcul, chaque titre est normalisé :

```python
text = text.lower()
text = re.sub(r"[^\w\s]", " ", text)   # supprime ponctuation
tokens = [t for t in text.split() if t not in STOP_WORDS]
```

**Stop words supprimés** : `will, the, a, an, in, on, at, by, to, of, be, is, any, or, and, for, before, after, this, that, with, from`

---

## 2. Score textuel — `token_sort_ratio`

Fonction : `rapidfuzz.fuzz.token_sort_ratio(a, b)` → `[0, 100]`

1. **Tokenisation** : découpe en mots
2. **Tri alphabétique** des tokens (neutralise l'ordre des mots)
3. **Ratio de Levenshtein** entre les deux chaînes triées

---

## 3. Score de date — décroissance exponentielle

```
score_date = 100 × 0.05^(|Δjours| / DATE_DECAY_DAYS)
```

Avec `DATE_DECAY_DAYS = 365`.

| Écart entre les dates | Score date |
|---|---|
| 0 jours (même date) | **100.0** |
| 30 jours | 22.6 |
| 180 jours | 2.3 |
| Date manquante | **50.0** (neutre) |

> **Pourquoi date à 10 % ?**
> Kalshi utilise des dates de clôture arbitraires (parfois 2029 pour un marché 2026).
> Le texte reste le signal principal ; la date ne sert que de léger tiebreaker.

---

## 4. Score final

```
score_final = 0.90 × score_texte + 0.10 × score_date
```

### Seuil : 65 / 100

En dessous de 65, la paire est rejetée.

---

## 5. Filtres de pré-sélection

### Catégorie normalisée

Chaque marché est assigné à une catégorie normalisée :

| Catégorie | PM tags | KS categories |
|---|---|---|
| `sports` | Sports, Soccer, NBA, NFL… | Sports |
| `politics` | Politics, Elections… | Elections, Politics |
| `crypto` | Crypto, Bitcoin, Ethereum… | Crypto |
| `weather` | Weather, Daily Temperature | Climate and Weather |
| `economics` | Economics, Finance | Economics, Financials |
| `entertainment` | Culture, Entertainment | Entertainment |
| `companies` | Companies | Companies |
| `world` | World | World |
| `other` | (reste) | (reste) |

Un match est rejeté si les catégories sont incompatibles (sauf si l'une des deux est `other`).

### Entités nommées

Chaque titre est parsé pour en extraire les **noms propres** (mots capitalisés ≥ 3 lettres, hors stop list) et les **nombres**.

Un match est rejeté si les deux côtés ont des entités mais aucune en commun.

### Exclusions spécifiques

- **Polymarket** : marchés "Up or Down", "up/down", heures intraday (ex: `5:30pm`)
- **Kalshi** : events scalaires (plusieurs marchés avec le même titre = brackets de prix)

---

## 6. Validation sémantique dure (gates)

Après le seuil de score, une validation stricte est appliquée par catégorie.
Un seul gate qui échoue → le match est rejeté, quelle que soit la similarité textuelle.

### Catégorie `weather` — 4 gates

| Gate | Logique | Exemple rejeté |
|---|---|---|
| **Date de référence** | Extrait la date du texte ("March 2", "Mar 1, 2026"), fallback sur `end_date`. Rejette si les dates diffèrent. | PM=2026-03-02, KS=2026-03-01 |
| **Direction métrique** | Détecte `high/highest/max` vs `low/min/minimum`. Rejette si opposés. | "highest temp" vs "minimum temp" |
| **Bucket température** | Extrait la plage numérique. Exige la **containment** (r1 ⊆ r2 ou r2 ⊆ r1), pas juste un chevauchement. | 82-83°F vs 81-82° (adjacents) |
| **Ville** | Si les deux titres ont des entités nommées, exige une intersection. | "Seoul … 6°C" vs titre sans ville |

#### Extraction de date depuis le texte

```python
# Patterns reconnus :
"on March 2"      → 2026-03-02
"Mar 1, 2026?"    → 2026-03-01
"March 2, 2026"   → 2026-03-02
# Fallback : end_date converti en date locale
```

#### Containment vs overlap pour les buckets

```
(82, 83) ⊆ (81, 82) ? → NON  → rejeté  ✓
(84, 85) ⊆ (84, 85) ? → OUI  → accepté ✓
(28, 28) ⊆ (28, 29) ? → OUI  → accepté ✓  (PM: "28°C", KS: "28-29°")
```

---

## 7. Calcul d'arbitrage

```
YES_PM + NO_KS  → profit = 1 - (pm_yes_ask + ks_no_ask)
NO_PM  + YES_KS → profit = 1 - (pm_no_ask  + ks_yes_ask)
```

- `pm_no_ask ≈ 1 - pm_yes_bid`
- `ks_no_ask` fourni directement par l'API Kalshi

Un `profit > 0` signifie un gain garanti avant frais.

### Exemple de sortie (`matches.json`)

```json
{
  "match_score": 95.8,
  "text_score": 95.3,
  "date_score": 100.0,
  "category": "politics",
  "arbitrage": {
    "best_profit": 0.04,
    "direction": "NO_PM + YES_KS",
    "yes_pm_no_ks": -0.01,
    "no_pm_yes_ks": 0.04
  },
  "polymarket": {
    "question": "Will Donald Trump endorse Ken Paxton for the Texas Republican Senate?",
    "end": "2026-03-02T...",
    "yes_ask": 0.14,
    "no_ask": 0.87
  },
  "kalshi": {
    "title": "Will Donald Trump endorse Ken Paxton in the 2026 Texas Senate Rep...",
    "end": "2026-03-03T...",
    "yes_ask": 0.09,
    "no_ask": 0.93
  }
}
```

---

## Paramètres configurables

| Constante | Valeur | Rôle |
|---|---|---|
| `W_TEXT` | 0.90 | Poids du score textuel |
| `W_DATE` | 0.10 | Poids du score de date |
| `SCORE_THRESHOLD` | 65.0 | Seuil minimum pour garder un match |
| `DATE_DECAY_DAYS` | 365 | Jours pour atteindre score_date ≈ 5 |
| `WITHIN_DAYS` | 3 | Fenêtre max de clôture (jours) |
