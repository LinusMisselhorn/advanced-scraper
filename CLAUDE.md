# CLAUDE.md

Kontext und Konventionen für KI-Sessions in diesem Repo.

## Projekt

IMPRESSION ist eine Zwei-Personen-Beratung aus Salzgitter (Growth Partner, keine Marketingagentur). Zielkunden sind Kleinunternehmen bis ca. 20 Mitarbeiter, bei denen der Inhaber entscheidet. Verkauft wird ein besserer Auftritt: Website, Vertrauen, Professionalität.

Dieses Repo ist das Signal-Based-Outreach-System: Angerufen wird nur, wenn ein öffentliches Signal Wachstum oder Bedarf zeigt. Recruiting ist nicht das Produkt, eine Stellenanzeige ist nur der Gesprächsanlass.

Architektur: Scraper → Supabase (Postgres) → später HubSpot.

## Supabase

- Projekt: `yaxuexpptzinmykswrmw` (https://yaxuexpptzinmykswrmw.supabase.co)
- `companies`: id, name, domain (UNIQUE), website, has_website, category, industry, street, postal_code, city, phone, rating, reviews_count, google_place_id (UNIQUE), source, employees_est, is_fit, hubspot_id, created_at
- `signals`: id, company_id, signal_type_id, source, url, detected_at, raw (jsonb), UNIQUE(company_id, signal_type_id, url)
- `signal_types`: id, name, tier, base_weight, opener
- `lead_scores`, `call_outcomes`: für Scoring und Rückmeldung aus Telefonaten

### signal_type_ids

| id | Quelle |
|---|---|
| 1003 | Indeed-Stellenanzeige (`scraper/indeed_jobspy.py`) |

Weitere IDs stehen in `public.signal_types`. Neue Konstanten gehören nach `scraper/config.py`.

## Konventionen

- Doku und Kommentare auf Deutsch, Code-Bezeichner dürfen englisch sein.
- Keine Gedankenstriche (weder Halbgeviert- noch Geviertstrich) in Doku, Kommentaren und Commit-Messages. Stattdessen Komma, Doppelpunkt, Klammer oder neuer Satz.
- Keine Secrets im Repo. Keys nur in `.env` (ist in `.gitignore`), `.env.example` enthält nur Platzhalter.
- Schreibzugriffe auf Supabase nur über den Scraper mit Service-Role-Key, nicht über MCP-Tools. Schemaänderungen nur nach Absprache.
- Jeder Scraper braucht `--dry-run`, muss idempotent sein und Duplikate über UNIQUE-Constraints abfangen.
- Tests mit pytest, ohne Netzwerk. Externe Quellen über Fixtures im Format der jeweiligen Bibliothek nachbilden.
- Kleine, saubere Commits auf Feature-Branches, nicht direkt auf main.

## Neue Signalquellen

Geplant sind weitere Quellen (Meta-Ads, lokale Werbung, Portale). Muster für ein neues Modul:

1. `scraper/<quelle>.py` mit Abruf, Qualifizierung über `qualify.py` und Abgleich über `matching.CompanyIndex`
2. eigene signal_type_id in `config.py` und in der Tabelle oben
3. Fixture unter `tests/fixtures/` und Tests

## Bekannte Grenzen

- In Sandbox-Umgebungen ist Indeed über die Netzwerk-Allowlist gesperrt. Nicht umgehen (kein Proxy, kein Mirror), sondern mit `--fixture` testen.
- Indeed liefert keine Postleitzahl und keine Telefonnummer. Diese Felder bleiben bei neuen Firmen leer und müssen später angereichert werden (z. B. Google Places).
