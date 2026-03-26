# ProjectKompas

ProjectKompas is een maakbaarheidstool voor infraprojecten. De applicatie helpt projectteams om vroegtijdig te zien of een project waarschijnlijk haalbaar is qua planning, budget en risico, op basis van vergelijking met soortgelijke projecten.

## Samenvatting voor niet-technische lezers

### Wat doet deze tool?

- Je kiest een project.
- De tool zoekt vergelijkbare projecten.
- Je krijgt drie duidelijke signalen (groen/oranje/rood):
  - Is de geplande buitendienststelling realistisch?
  - Is de klanteis haalbaar?
  - Blijven we waarschijnlijk binnen budget?
- Je krijgt ook een overzicht van de belangrijkste risico's.

### Waarom is dit relevant voor ProRail?

- Besluitvorming wordt consistenter en minder afhankelijk van onderbuikgevoel.
- Projectteams zien eerder waar bijsturing nodig is.
- Door data uit Microsoft-omgevingen te gebruiken sluit de tool aan op bestaande ProRail-processen.

### Wat is er nodig om dit succesvol te maken?

- Duidelijk eigenaarschap (business + IT + data).
- Toegang tot betrouwbare brondata in Microsoft Dataverse.
- Vaste werkwijze voor wijzigingen (Azure DevOps pipelines, code reviews, testen).
- Budget voor doorontwikkeling, beheer, monitoring en support.

### Verwachte opbrengst

- Sneller inzicht in projectrisico's.
- Betere prioritering van maatregelen.
- Minder herstelwerk later in het project.
- Betere onderbouwing richting stakeholders.

---

## Technische handleiding (ProRail / Microsoft / Azure DevOps)

## 1. Doel en scope

Deze repository bevat:

- Een Streamlit-app (`app.py`) voor gebruikersinteractie en analyseweergave.
- Een feature-pipeline (`build_features.py`) die projectprofielen opbouwt.
- Tests en hulpfuncties voor dataverwerking.

Primair doel: een reproduceerbare, uitlegbare maakbaarheidsanalyse per project met peervergelijking.

## 2. Architectuur op hoofdlijnen

```text
Gebruiker kiest ProjectID
    ->
Datalaag ophalen (Dataverse / bronbestanden)
    ->
Feature-opbouw per project
    ->
Similarity matching (top-k vergelijkbare projecten)
    ->
KPI-berekening + risicoprofiel
    ->
Visualisatie in Streamlit
```

## 3. Databronnen en doelarchitectuur

### Huidige situatie

- CSV/Excel bronbestanden in `data/`.

### Doelsituatie (ProRail)

- Microsoft Dataverse als primaire, beheerde bron.
- Incrementele extracties naar featurelaag.
- Versiebeheer van afgeleide datasets voor audit/reproduceerbaarheid.

## 4. Installatie (lokaal ontwikkelgebruik)

### Vereisten

- Python 3.10+
- `pip`
- Git
- (Optioneel) Conda

### Installatiestappen

```bash
git clone <repo-url>
cd projectkompas
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python build_features.py
streamlit run app.py
```

App start standaard op `http://localhost:8501`.

## 5. Gebruik van de applicatie

1. Selecteer een `ProjectID`.
2. Controleer kerngegevens (gebied, complexiteit, budget, planning).
3. Start analyse.
4. Lees de KPI-stoplichten:
   - TVP voldoende?
   - Klanteis haalbaar?
   - Binnen budget?
5. Bekijk risicotabel + peer-risicoprofiel.
6. Leg maatregelen vast in projectoverleg.

## 6. Similarity matching algoritme (vereiste doorontwikkeling)

Er moet een expliciet similarity-model worden geimplementeerd om vergelijkbare projecten objectief te selecteren.

### Minimale technische opzet

- Featuregroepen:
  - Numeriek: budget, TVP-duur, planning-slack, ratio's.
  - Categorieel: gebied, complexiteit, segment, TESI-code.
  - Optioneel tekst: scope/risico-kenmerken.
- Preprocessing:
  - Schalen van numerieke features.
  - Coderen van categorische features.
  - Imputatie voor missende waarden.
- Similarity:
  - Start met cosine similarity op gecombineerde featurevector.
  - Top-k peers (bijv. `k=20`) met minimumscore.
- Uitlegbaarheid:
  - Per peer matchscore en featurebijdrage tonen.
  - Redencode opslaan voor audit.

### Aanbevolen output

- `peer_matches` met velden: `project_id`, `peer_id`, `score`, `rank`, `reason_codes`, `run_timestamp`.

## 7. Integratie met Microsoft Dataverse (vereiste)

### Doel

Alle kerndata voor projectanalyse centraal ontsluiten vanuit Dataverse in plaats van losse bestanden.

### Integratiepatroon

1. Authenticatie via Entra ID (service principal of managed identity).
2. Data ophalen via Dataverse Web API (OData + paging).
3. Incrementele sync op `modifiedon`.
4. Schema-validatie en datakwaliteitscontroles.
5. Feature-opbouw uitvoeren.
6. Output opslaan voor hergebruik en auditing.

### Configuratie (voorbeeld)

- `DATAVERSE_BASE_URL`
- `DATAVERSE_TENANT_ID`
- `DATAVERSE_CLIENT_ID`
- `DATAVERSE_CLIENT_SECRET`
- `DATAVERSE_SCOPE`

Secrets nooit in code of repo; gebruik Azure Key Vault.

## 8. ProRail-specifieke Azure DevOps inrichting

### Repositories en branches

- `main` beschermd.
- Feature branches per wijziging.
- Pull requests verplicht.
- Minimaal 1-2 reviewers.

### Branch policies

- Build-validatie verplicht.
- Geen directe pushes op `main`.
- PR-templates met testbewijs en impactanalyse.

### CI pipeline (minimaal)

- Install dependencies.
- Run lint/checks.
- Run unit tests.
- Build artefact/container image.

### CD pipeline (minimaal)

- Uitrol naar `dev` -> `test/accept` -> `prod`.
- Approvals/gates tussen omgevingen.
- Rollbackstrategie en release-notes verplicht.

## 9. Omgevingen en beheer

### Omgevingsmodel

- `dev`: ontwikkeling.
- `test`: integratie en regressie.
- `accept`: businessvalidatie/UAT.
- `prod`: operationeel gebruik.

### Monitoring

- Azure Monitor + Log Analytics.
- Alerts op:
  - falende data-refresh;
  - hoge foutpercentages;
  - onbeschikbaarheid van de app.

### Continuiteit

- Back-up en restore-test periodiek uitvoeren.
- RTO/RPO expliciet afspreken.
- Runbooks voor incidenten en herstel.

## 10. Benodigde ondersteuning (budget en organisatie)

## Financieel (indicatief)

- Tooling/licenties:
  - IDE (bijv. Cursor) of andere enterprise IDE.
  - Azure DevOps.
  - Dataverse capaciteit.
- Platform:
  - Compute voor app + pipeline.
  - Opslag + monitoring + Key Vault.
- Menscapaciteit:
  - Product owner (business).
  - Data engineer.
  - Developer(s).
  - Test/acceptatie ondersteuning.
  - DevOps support.

Indicatief voor eerste productieronde (8-12 weken): 1-2 technische FTE plus business/test-inzet.

## Niet-financieel

- Toegang tot databronnen en beheerders.
- Duidelijk mandaat voor prioritering.
- Beschikbaarheid van eindgebruikers voor UAT.
- Governance op datakwaliteit en definities.

## 11. Werken met Cursor of andere IDE

### Aanbevolen ontwikkelproces

- Kleine, reviewbare PR's.
- Standaard commands voor format/lint/test.
- Wijzigingen eerst in `dev`, daarna promotie via pipeline.
- Documenteer ontwerpkeuzes in repo (README/ADR).

### Kwaliteitswaarborgen

- Pre-commit checks lokaal.
- Verplichte CI pass voor merge.
- Testevidence in PR.
- Functionele check door business bij impactvolle wijzigingen.

## 12. Roadmap om af te ronden

### Fase 1 - Stabiliseren

- Datavalidatie, logging, extra tests, reproduceerbare pipeline.

### Fase 2 - Slimmere vergelijkingen

- Similarity matching implementeren + uitlegbaarheid in UI.

### Fase 3 - Microsoft integratie

- Dataverse als primaire bron + incrementele sync.

### Fase 4 - Productie en beheer

- Azure DevOps CI/CD volledig, monitoring, runbooks, beheerorganisatie.

## 13. Acceptatiecriteria voor "productierijp"

- Similarity matching aantoonbaar actief in analyses.
- Dataverse-integratie operationeel met incrementele updates.
- CI/CD volledig geautomatiseerd in Azure DevOps.
- Security-baseline op orde (secrets, rechten, auditing).
- Beheerproces en incidentrespons ingericht.
- UAT formeel akkoord door business.

## 14. Bestanden in deze repo

| Bestand | Functie |
|---|---|
| `app.py` | Streamlit-interface voor projectanalyse |
| `build_features.py` | Data-loaders en feature-opbouw |
| `utils/io_utils.py` | Veilige read/write hulpfuncties |
| `utils/text_features.py` | Tekstkenmerken |
| `tests/test_build_features.py` | Testset voor pipeline-logica |
| `data/project_profiles.csv` | Gegenereerde feature-output |

