# ProjectKompas v2 — Maakbaarheidstool

Streamlit-app die per infraproject een **maakbaarheidsanalyse** uitvoert op basis van peer-vergelijking met vergelijkbare projecten.

## Architectuur

```
Gebruiker voert ProjectID in
    ↓
┌─────────────────────────────────────┐
│  Lookup project-karakteristieken    │
│  Ordertaken / BDS / DimPlanning /   │
│  DimGeld / DimInfra / Risicodossier │
└────────────────┬────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│  Vergelijkbare projecten zoeken     │
│  (Geo-peers + TESI-code-peers)      │
└────────────────┬────────────────────┘
                 ↓
    ┌────────────┴────────────┐
    ↓                         ↓
 3 KPI stoplichten      Risico-lijst
 - TVP voldoende?       - Kans × Impact
 - Klanteis haalbaar?   - Peer-profiel
 - Binnen budget?
```

## Databronnen

| Bron | Join-key | Levert |
|---|---|---|
| Ordertaken.csv | ProjectID (genormaliseerd) | Geo, TESI code, Budget |
| FactBuitendienststellingen.csv | ProjectID | TVP Duur |
| DimPlanning.xlsx | ProjectID | Plandatum, Klanteis, HaalbaarheidBoolean |
| DimGeld.xlsx | ProjectID | Prognose eindstand, budget_ratio |
| DimInfraprojecten.xlsx | ProjectID | Complexiteit, Marktsegment, Gebied |
| Risicodossier.xlsx | ProjectID | Kans, EV_geld, EV_tijd, Status |

## Quickstart

```bash
# 1. Conda-environment activeren
conda activate eip

# 2. Dependencies installeren
pip install -r requirements.txt

# 3. Projectprofielen genereren
python build_features.py

# 4. App starten
streamlit run app.py
```

## Schermen

### Scherm 1 — Projectgegevens
- Selecteer een ProjectID uit de dropdown
- Bekijk projectprofiel: complexiteit, gebied, budget, planning, TVPs
- Klik "Analyseer maakbaarheid" om door te gaan

### Scherm 2 — Maakbaarheidsanalyse
- **3 KPI-kaarten** (groen/oranje/rood stoplicht):
  - **TVP voldoende?** — TVP-duur vergeleken met P25/P50/P75 van Geo-peers
  - **Klanteis haalbaar?** — Slack in dagen vergeleken met Complexiteit-peers
  - **Binnen budget?** — Budget-ratio vergeleken met peer-verdeling
- **Risico-tabel** — Projectspecifieke risico's, gesorteerd op EV (geld)
- **Peer-risicoprofiel** — Top risico-thema's uit vergelijkbare projecten

## Tests

```bash
pytest tests/ -v
```

## Bestanden

| Bestand | Functie |
|---|---|
| `build_features.py` | 6 data-loaders, PID-normalisatie, peer-matching, 3 KPI-berekeningen |
| `app.py` | Streamlit UI: Scherm 1 (invoer) + Scherm 2 (analyse) |
| `utils/io_utils.py` | Safe Excel/CSV read/write wrappers |
| `utils/text_features.py` | Keyword extraction uit vrije tekst |
| `tests/test_build_features.py` | 35 tests: loaders, aggregaties, peers, KPIs |
| `data/project_profiles.csv` | Gegenereerde projectprofielen (output van build_features.py) |
