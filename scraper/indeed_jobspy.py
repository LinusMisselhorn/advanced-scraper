"""Indeed-Stellenanzeigen als Bedarfssignal (signal_type_id 1003).

Holt über JobSpy alle Stellenanzeigen im Umkreis von Salzgitter, filtert
Großarbeitgeber und Personaldienstleister heraus, gleicht die Firmen gegen
public.companies ab und schreibt Signale nach Supabase.

Aufruf:
    python -m scraper.indeed_jobspy --dry-run
    python -m scraper.indeed_jobspy --dry-run --fixture tests/fixtures/indeed_salzgitter_sample.json
    python -m scraper.indeed_jobspy
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import SIGNAL_TYPE_INDEED, SOURCE_INDEED, Settings, load_settings
from .matching import CompanyIndex, CompanyRecord, MatchResult, extract_domain, same_city
from .qualify import employees_estimate, qualify_job

log = logging.getLogger("scraper.indeed")

# Diese Domains sind keine eigene Firmenwebsite und werden nicht als website gespeichert.
NON_COMPANY_DOMAINS = (
    "indeed.com",
    "indeed.de",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "xing.com",
    "stepstone.de",
    "google.com",
)

NEW_ID_PREFIX = "neu:"


# ---------------------------------------------------------------------------
# Datenbeschaffung
# ---------------------------------------------------------------------------


def fetch_jobs(settings: Settings) -> pd.DataFrame:
    """Ruft Indeed über JobSpy ab. Ein Aufruf pro Suchbegriff, leerer Begriff = alle Stellen."""
    from jobspy import scrape_jobs  # Import hier, damit Tests ohne Netzwerk laufen

    terms: list[str | None] = list(settings.search_terms) or [None]
    frames: list[pd.DataFrame] = []
    errors: dict[str, Any] = {}
    for term in terms:
        log.info(
            "Indeed-Suche: Begriff=%r, Ort=%r, Radius=%s km (%s mi), letzte %s Tage",
            term or "", settings.location, settings.radius_km, settings.radius_miles, settings.days,
        )
        df = scrape_jobs(
            site_name=["indeed"],
            search_term=term,
            location=settings.location,
            distance=settings.radius_miles,
            hours_old=settings.hours_old,
            results_wanted=settings.results_wanted,
            country_indeed=settings.country_indeed,
            description_format="markdown",
            verbose=1,
        )
        site_errors = (df.attrs or {}).get("errors") or {}
        if site_errors:
            errors[term or ""] = site_errors
            log.warning("JobSpy meldet Fehler für Begriff %r: %s", term or "", site_errors)
        frames.append(df)

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not result.empty and "job_url" in result.columns:
        result = result.drop_duplicates(subset=["job_url"]).reset_index(drop=True)
    result.attrs = {"errors": errors}
    return result


def load_fixture(path: str | Path) -> pd.DataFrame:
    """Lädt einen Fixture-Datensatz im JobSpy-DataFrame-Format (JSON, orient=records)."""
    with open(path, encoding="utf-8") as fh:
        records = json.load(fh)
    df = pd.DataFrame(records)
    df.attrs = {"errors": {}}
    return df


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame-Zeilen als dicts, NaN und NaT werden zu None."""
    records = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for key, value in row.items():
            if value is None or (isinstance(value, float) and math.isnan(value)):
                clean[key] = None
            elif value is pd.NaT:
                clean[key] = None
            else:
                clean[key] = value
        records.append(clean)
    return records


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def parse_city(location: str | None) -> str | None:
    """JobSpy liefert den Ort als "Salzgitter, NI, DE". Erster Teil ist die Stadt."""
    if not location:
        return None
    city = str(location).split(",")[0].strip()
    return city or None


def company_website(job: dict) -> str | None:
    url = job.get("company_url_direct")
    domain = extract_domain(url)
    if not domain:
        return None
    if any(domain == d or domain.endswith("." + d) for d in NON_COMPANY_DOMAINS):
        return None
    return str(url)


def to_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return to_iso_date(parsed if isinstance(parsed, datetime) else parsed)


def truncate(text: str | None, max_chars: int) -> str | None:
    if not text:
        return None
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Planung (ohne Schreibzugriffe)
# ---------------------------------------------------------------------------


@dataclass
class PlannedSignal:
    job: dict
    company_key: str  # echte companies.id oder Platzhalter "neu:<normalisiert>"
    company_name: str
    match: MatchResult | None
    is_new_company: bool
    is_fit: bool | None
    signal: dict

    def summary(self) -> dict:
        return {
            "firma": self.job.get("company"),
            "titel": self.job.get("title"),
            "ort": self.job.get("location"),
            "datum": self.signal.get("detected_at"),
            "mitarbeiter": self.job.get("company_num_employees"),
            "abgleich": (
                {
                    "methode": self.match.method,
                    "score": round(self.match.score, 1),
                    "company_id": self.match.company.id,
                    "bestehende_firma": self.match.company.name,
                }
                if self.match
                else "neue Firma"
            ),
            "is_fit": self.is_fit,
            "url": self.signal.get("url"),
        }


@dataclass
class Plan:
    planned: list[PlannedSignal] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    new_companies: dict[str, dict] = field(default_factory=dict)  # Platzhalter → Zeile


def build_signal(job: dict, settings: Settings, match: MatchResult | None) -> dict:
    detected_at = to_iso_date(job.get("date_posted")) or datetime.now(timezone.utc).isoformat()
    raw = {
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "date_posted": to_iso_date(job.get("date_posted")),
        "description": truncate(job.get("description"), settings.description_max_chars),
        "job_url_direct": job.get("job_url_direct"),
        "job_type": job.get("job_type"),
        "is_remote": job.get("is_remote"),
        "company_num_employees": job.get("company_num_employees"),
        "company_industry": job.get("company_industry"),
        "jobspy_id": job.get("id"),
        "match_method": match.method if match else "new",
        "match_score": round(match.score, 1) if match else None,
    }
    return {
        "signal_type_id": SIGNAL_TYPE_INDEED,
        "source": SOURCE_INDEED,
        "url": job.get("job_url"),
        "detected_at": detected_at,
        "raw": raw,
    }


def build_plan(records: list[dict], settings: Settings, index: CompanyIndex) -> Plan:
    """Qualifiziert und gleicht ab. Neue Firmen landen als Platzhalter im Index,
    damit mehrere Anzeigen derselben Firma nur eine neue Firma erzeugen."""
    plan = Plan()
    seen_urls: set[str] = set()
    known_domains = {r.domain for r in index.records if r.domain}

    for job in records:
        url = job.get("job_url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        verdict = qualify_job(job, settings)
        if not verdict.ok:
            plan.excluded.append(
                {"firma": job.get("company"), "titel": job.get("title"), "grund": verdict.reason, "url": url}
            )
            continue

        city = parse_city(job.get("location"))
        website = company_website(job)
        match = index.match(job.get("company"), city=city, website=website)

        is_new = match is None or match.company.id.startswith(NEW_ID_PREFIX)
        if match is None:
            name = " ".join(str(job["company"]).split())
            domain = extract_domain(website)
            if domain in known_domains:
                domain = None  # UNIQUE(domain) nicht verletzen
            placeholder = CompanyRecord(id="", name=name, city=city, domain=domain)
            placeholder.id = f"{NEW_ID_PREFIX}{placeholder.normalized}"
            index.add(placeholder)
            if domain:
                known_domains.add(domain)
            plan.new_companies[placeholder.id] = {
                "name": name,
                "website": website,
                "has_website": True if website else None,
                "domain": domain,
                "category": job.get("company_industry"),
                "city": city,
                "source": SOURCE_INDEED,
                "employees_est": employees_estimate(job.get("company_num_employees")),
                "is_fit": same_city(city, settings.fit_city),
            }
            company_key, company_name = placeholder.id, name
            is_fit = plan.new_companies[placeholder.id]["is_fit"]
            shown_match = None
        else:
            company_key, company_name = match.company.id, match.company.name
            is_fit = plan.new_companies[company_key]["is_fit"] if is_new else None
            # Treffer auf einen Platzhalter derselben Laufzeit ist kein Abgleich mit Bestand
            shown_match = None if is_new else match

        plan.planned.append(
            PlannedSignal(
                job=job,
                company_key=company_key,
                company_name=company_name,
                match=shown_match,
                is_new_company=is_new,
                is_fit=is_fit,
                signal=build_signal(job, settings, shown_match),
            )
        )
    return plan


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------


def persist(plan: Plan, client) -> dict:
    """Legt neue Firmen an und schreibt die Signale. Idempotent durch
    Abgleich gegen Bestand (Firmen) und UNIQUE-Constraint (Signale)."""
    id_map: dict[str, str] = {}
    for key, row in plan.new_companies.items():
        payload = {k: v for k, v in row.items() if v is not None}
        created = client.insert_company(payload)
        id_map[key] = created["id"]
        log.info("Neue Firma angelegt: %s (%s)", row["name"], created["id"])

    signals = []
    for item in plan.planned:
        company_id = id_map.get(item.company_key, item.company_key)
        signals.append({"company_id": company_id, **item.signal})
    inserted = client.insert_signals(signals)
    return {
        "neue_firmen": len(id_map),
        "signale_gesendet": len(signals),
        "signale_neu": inserted,
        "signale_duplikat": len(signals) - inserted,
    }


# ---------------------------------------------------------------------------
# Ausgabe und CLI
# ---------------------------------------------------------------------------


def format_table(rows: list[dict]) -> str:
    if not rows:
        return "(keine qualifizierten Treffer)"
    headers = ["Firma", "Titel", "Ort", "Datum", "MA", "Abgleich", "Fit"]
    lines = []
    for r in rows:
        match = r["abgleich"]
        match_text = match if isinstance(match, str) else f"{match['methode']} {match['score']}"
        lines.append(
            [
                str(r["firma"] or "")[:32],
                str(r["titel"] or "")[:40],
                str(r["ort"] or "")[:22],
                str(r["datum"] or "")[:10],
                str(r["mitarbeiter"] or "")[:12],
                match_text[:16],
                "" if r["is_fit"] is None else ("ja" if r["is_fit"] else "nein"),
            ]
        )
    widths = [max(len(h), *(len(l[i]) for l in lines)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    out += [fmt.format(*l) for l in lines]
    return "\n".join(out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m scraper.indeed_jobspy",
        description="Indeed-Stellenanzeigen kleiner Betriebe als Signal nach Supabase schreiben.",
    )
    p.add_argument("--dry-run", action="store_true", help="nichts schreiben, nur Treffer ausgeben")
    p.add_argument("--fixture", help="statt Indeed einen lokalen JSON-Datensatz verwenden")
    p.add_argument("--location", help="Suchort (Default: Salzgitter, Niedersachsen)")
    p.add_argument("--radius-km", type=int, help="Umkreis in km (Default: 15)")
    p.add_argument("--days", type=int, help="nur Anzeigen der letzten N Tage (Default: 14)")
    p.add_argument(
        "--search-term", action="append", dest="search_terms",
        help="Suchbegriff, mehrfach möglich. Ohne Angabe: alle Stellen",
    )
    p.add_argument("--results-wanted", type=int, help="max. Treffer pro Suchbegriff (Default: 300)")
    p.add_argument("--max-employees", type=int, help="Mitarbeitergrenze (Default: 20)")
    p.add_argument("--match-threshold", type=int, help="Fuzzy-Schwellwert 0 bis 100 (Default: 90)")
    p.add_argument("--format", choices=["json", "table"], default="json", help="Ausgabeformat im Dry-Run")
    p.add_argument("--show-excluded", action="store_true", help="ausgeschlossene Anzeigen mit Grund ausgeben")
    p.add_argument("--no-db", action="store_true", help="im Dry-Run keinen Bestand aus Supabase laden")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    for attr in ("location", "radius_km", "days", "search_terms", "results_wanted", "max_employees", "match_threshold"):
        value = getattr(args, attr)
        if value is not None:
            setattr(settings, attr, value)
    return settings


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    settings = apply_overrides(load_settings(), args)

    # Bestand laden (im Dry-Run nur lesend und optional)
    client = None
    index = CompanyIndex(threshold=settings.match_threshold)
    has_creds = bool(settings.supabase_url and settings.supabase_service_role_key)
    if not args.dry_run and not has_creds:
        log.error("Für den Schreibmodus müssen SUPABASE_URL und SUPABASE_SERVICE_ROLE_KEY gesetzt sein.")
        return 1
    if has_creds and not args.no_db:
        from .supabase_client import SupabaseClient

        client = SupabaseClient(settings.supabase_url, settings.supabase_service_role_key)
        for row in client.fetch_companies():
            index.add(CompanyRecord(id=row["id"], name=row.get("name") or "", city=row.get("city"), domain=row.get("domain")))
        log.info("%s bestehende Firmen geladen", len(index.records))
    elif args.dry_run:
        log.warning("Kein Supabase-Zugang konfiguriert: Abgleich nur innerhalb dieses Laufs.")

    # Anzeigen holen
    if args.fixture:
        log.info("Verwende Fixture %s statt Indeed", args.fixture)
        df = load_fixture(args.fixture)
    else:
        try:
            df = fetch_jobs(settings)
        except Exception as exc:  # JobSpy wirft je nach Fehlerart unterschiedliche Typen
            log.error("Indeed-Abruf fehlgeschlagen: %s: %s", type(exc).__name__, exc)
            return 2
        if df.empty and df.attrs.get("errors"):
            log.error("Indeed-Abruf ohne Ergebnis, Fehler: %s", df.attrs["errors"])
            return 2

    records = dataframe_to_records(df)
    plan = build_plan(records, settings, index)
    log.info(
        "%s Anzeigen, %s qualifiziert, %s ausgeschlossen, %s neue Firmen",
        len(records), len(plan.planned), len(plan.excluded), len(plan.new_companies),
    )

    if args.dry_run:
        rows = [p.summary() for p in plan.planned]
        if args.format == "table":
            print(format_table(rows))
            if args.show_excluded:
                print("\nAusgeschlossen:")
                for e in plan.excluded:
                    print(f"  {str(e['firma'] or '(ohne Namen)')[:40]:<40}  {e['grund']}")
        else:
            out: dict[str, Any] = {"qualifiziert": rows, "neue_firmen": list(plan.new_companies.values())}
            if args.show_excluded:
                out["ausgeschlossen"] = plan.excluded
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    stats = persist(plan, client)
    log.info("Fertig: %s", stats)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
