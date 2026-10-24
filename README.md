# advanced-scraper

Signal-Based-Outreach-System von IMPRESSION. Statt Kaltakquise wird ein Betrieb nur dann angerufen, wenn ein öffentliches Signal Wachstum oder Bedarf zeigt. Dieses Repo sammelt solche Signale und legt sie in Supabase ab. Später werden qualifizierte Leads nach HubSpot übertragen.

Architektur: **Scraper → Supabase (Postgres) → HubSpot**

## Modul 1: Indeed-Stellenanzeigen

Eine Stellenanzeige eines kleinen Betriebs ist ein Gesprächsanlass: Der Betrieb wächst, sucht Bewerber, und Bewerber schauen sich den Betrieb online an. Recruiting selbst ist nicht das Produkt, die Anzeige liefert nur den Anlass für das Gespräch über Website, Vertrauen und Auftritt.

Der Scraper nutzt die Bibliothek [JobSpy](https://github.com/speedyapply/JobSpy) (`python-jobspy`) und arbeitet in vier Schritten:

1. **Abruf**: Alle Indeed-Anzeigen im Umkreis von Salzgitter aus den letzten N Tagen.
2. **Qualifizierung**: Großarbeitgeber, Ketten, öffentliche Hand und Personaldienstleister fallen heraus. Liefert Indeed eine Mitarbeiterzahl und liegt deren Untergrenze über der Grenze (Default 20), fällt die Firma ebenfalls heraus.
3. **Firmen-Abgleich** gegen `public.companies`:
   - Domain der Firmenwebsite (falls Indeed sie liefert) gegen `companies.domain`
   - normalisierter Name exakt (Rechtsformen wie GmbH, GbR, e.K., GmbH & Co. KG entfernt, Kleinschreibung, Umlaute als ae/oe/ue/ss, Zusatz "Inh. ..." entfernt)
   - Fuzzy-Match mit rapidfuzz (`token_sort_ratio`, Default Schwellwert 90). Sind beide Orte bekannt und verschieden, zählt nur ein Score von 100.
   - Kein Treffer: neue Firma mit `source = 'indeed'`, `is_fit = true` nur bei Ort Salzgitter (inklusive Stadtteile wie Salzgitter-Bad).
4. **Signal** in `public.signals`: `signal_type_id = 1003`, `source = 'indeed'`, `url` = Job-URL, `detected_at` = Veröffentlichungsdatum, `raw` = Titel, Ort, Datum, gekürzte Beschreibung und Abgleich-Infos.

Läufe sind idempotent: Firmen aus früheren Läufen werden über den Abgleich wiedergefunden, doppelte Signale verhindert `UNIQUE(company_id, signal_type_id, url)` (PostgREST `on_conflict` mit `ignore-duplicates`).

## Setup

Voraussetzung: Python 3.11 oder neuer.

```bash
git clone https://github.com/LinusMisselhorn/advanced-scraper.git
cd advanced-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env öffnen und SUPABASE_SERVICE_ROLE_KEY eintragen
```

Den Service-Role-Key gibt es im Supabase-Dashboard unter Project Settings, API. Er umgeht RLS und gehört nur in die `.env` bzw. in die Secrets des Servers, niemals ins Repo.

## Konfiguration

Reihenfolge: Default, dann Umgebungsvariable, dann CLI-Argument.

| Parameter | Umgebungsvariable | CLI | Default |
|---|---|---|---|
| Suchort | `INDEED_LOCATION` | `--location` | Salzgitter, Niedersachsen |
| Umkreis in km | `INDEED_RADIUS_KM` | `--radius-km` | 15 |
| Zeitraum in Tagen | `INDEED_DAYS` | `--days` | 14 |
| Suchbegriffe (Komma-Liste) | `INDEED_SEARCH_TERMS` | `--search-term` (mehrfach) | leer, also alle Stellen |
| Treffer pro Suchbegriff | `INDEED_RESULTS_WANTED` | `--results-wanted` | 300 |
| Mitarbeitergrenze | `INDEED_MAX_EMPLOYEES` | `--max-employees` | 20 |
| Fuzzy-Schwellwert | `INDEED_MATCH_THRESHOLD` | `--match-threshold` | 90 |

Ausschlusslisten (Großarbeitgeber, Namens-Stichwörter wie "personal" oder "zeitarbeit", typische Formulierungen wie "im Auftrag unseres Kunden") stehen in `scraper/config.py` und lassen sich dort pflegen.

Hinweise zu JobSpy und Indeed:

- JobSpy übergibt den Radius an Indeed in Meilen. Der Scraper rechnet km in Meilen um und rundet auf (15 km ergeben 10 Meilen).
- Ohne Suchbegriff liefert Indeed alle Stellen im Umkreis. Pro Suche gibt Indeed maximal ca. 1000 Treffer heraus. Reicht das nicht, mehrere Suchbegriffe setzen (z. B. Branchen wie "Handwerk", "Friseur", "Pflege").
- Bei Indeed lässt sich `hours_old` nicht mit `job_type`/`is_remote` oder `easy_apply` kombinieren. Der Scraper nutzt nur `hours_old`.
- Die Mitarbeiterzahl kommt aus dem Indeed-Firmenprofil (`company_num_employees`, z. B. "11 bis 50") und fehlt bei vielen kleinen Betrieben. Spannen wie "11 bis 50" bleiben drin, weil die Untergrenze unter 20 liegt.

## Aufruf

```bash
# Nur anzeigen, nichts schreiben (liest den Bestand aus Supabase, falls Zugang gesetzt ist)
python -m scraper.indeed_jobspy --dry-run
python -m scraper.indeed_jobspy --dry-run --format table --show-excluded

# Ohne Netzwerk mit dem Beispieldatensatz testen
python -m scraper.indeed_jobspy --dry-run --fixture tests/fixtures/indeed_salzgitter_sample.json --format table --show-excluded

# Schreiben nach Supabase
python -m scraper.indeed_jobspy
```

Exit-Codes: `0` erfolgreich, `1` Konfiguration fehlt (Schreibmodus ohne Supabase-Zugang), `2` Indeed-Abruf fehlgeschlagen.

Logs gehen nach stderr, die Ergebnisse (JSON bzw. Tabelle) nach stdout. So lässt sich die Ausgabe direkt in n8n oder per `jq` weiterverarbeiten.

## Tests

```bash
pip install -r requirements.txt
python -m pytest
```

Die Tests laufen komplett ohne Netzwerk. `tests/fixtures/indeed_salzgitter_sample.json` enthält fiktive Beispielanzeigen im Spaltenformat des JobSpy-DataFrames.

## Betrieb (geplant)

Der Scraper soll außerhalb der Entwicklungsumgebung laufen, weil Indeed von Rechenzentrums-IPs teils blockiert und in Sandbox-Umgebungen per Allowlist gesperrt ist. Zwei Optionen:

**Variante A: kleiner Hetzner-VPS mit Cron**

```cron
# Täglich um 06:17 Uhr
17 6 * * * cd /opt/advanced-scraper && .venv/bin/python -m scraper.indeed_jobspy >> /var/log/advanced-scraper/indeed.log 2>&1
```

**Variante B: Aufruf aus n8n**

Ein n8n-Workflow mit Schedule-Trigger ruft per "Execute Command" (selbst gehostetes n8n auf demselben Server) `python -m scraper.indeed_jobspy` auf und verarbeitet die JSON-Statistik auf stdout weiter, z. B. für eine Benachrichtigung oder den späteren HubSpot-Push.

Falls Indeed die Server-IP blockiert, kennt JobSpy den Parameter `proxies`. Das ist bewusst noch nicht eingebaut und wäre eine eigene Entscheidung.

## Projektstruktur

```
scraper/
  config.py            Defaults, Ausschlusslisten, signal_type_ids
  matching.py          Namensnormalisierung und Firmen-Abgleich
  qualify.py           Ausschlusslogik und Mitarbeiterzahl
  supabase_client.py   dünne Schicht über die Supabase-REST-API
  indeed_jobspy.py     Abruf, Planung, Schreiben, CLI
tests/
  fixtures/indeed_salzgitter_sample.json
  test_*.py
```
