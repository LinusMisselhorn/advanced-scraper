"""Zentrale Konfiguration des Scrapers.

Alle Werte haben sinnvolle Defaults für den Standort Salzgitter. Sie lassen sich
über Umgebungsvariablen (bzw. eine lokale .env) und über CLI-Argumente
überschreiben. Reihenfolge: Default < Umgebungsvariable < CLI-Argument.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # python-dotenv ist optional, damit Tests ohne .env laufen
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# signal_type_ids aus der Tabelle public.signal_types
SIGNAL_TYPE_INDEED = 1003

SOURCE_INDEED = "indeed"

# Großarbeitgeber und Ketten in und um Salzgitter. Abgleich erfolgt auf dem
# normalisierten Namen als zusammenhängende Wortfolge, siehe qualify.py.
DEFAULT_EXCLUDED_EMPLOYERS: tuple[str, ...] = (
    # Industrie und Konzerne der Region
    "Salzgitter AG",
    "Salzgitter Flachstahl",
    "Salzgitter Mannesmann",
    "Peiner Träger",
    "Volkswagen",
    "VW",
    "Bosch",
    "MAN",
    "MAN Truck & Bus",
    "Alstom",
    "Siemens",
    "Continental",
    "IKEA",
    "Thyssenkrupp",
    "Linde",
    "Bundesgesellschaft für Endlagerung",
    "BGE",
    # Handel, Logistik, Systemgastronomie
    "Lidl",
    "Aldi",
    "Rewe",
    "Edeka",
    "Kaufland",
    "Netto",
    "Penny",
    "Rossmann",
    "dm drogerie markt",
    "Amazon",
    "DHL",
    "Deutsche Post",
    "Hermes",
    "DPD",
    "Deutsche Bahn",
    "McDonald's",
    "Burger King",
    "Hornbach",
    "Obi",
    "Toom",
    # Öffentliche Hand, Gesundheit, Finanzen
    "Stadt Salzgitter",
    "Landkreis Wolfenbüttel",
    "Bundeswehr",
    "Bundesagentur für Arbeit",
    "Helios",
    "Asklepios",
    "AOK",
    "Sparkasse",
    "Volksbank",
    "Deutsche Rentenversicherung",
    # Personaldienstleister und Zeitarbeit
    "Randstad",
    "Adecco",
    "Persona service",
    "Manpower",
    "ManpowerGroup",
    "Hays",
    "Orizon",
    "Tempton",
    "Amadeus Fire",
    "DIS AG",
    "Brunel",
    "Ferchau",
    "Gi Group",
    "Timepartner",
    "Trenkwalder",
    "Hofmann Personal",
    "I.K. Hofmann",
    "ARWA",
    "Piening",
    "Autovision",
    "Expertum",
    "Jobs in Time",
    "Akkurat",
    "Start People",
    "Kelly Services",
    "Robert Half",
    "Michael Page",
)

# Wortbestandteile im Firmennamen, die auf Personaldienstleister hindeuten.
# Abgleich als Teilzeichenkette im normalisierten Namen.
DEFAULT_EXCLUDED_NAME_KEYWORDS: tuple[str, ...] = (
    "personal",
    "zeitarbeit",
    "arbeitnehmerueberlassung",
    "recruit",
    "staffing",
    "headhunt",
    "jobvermittlung",
    "arbeitsvermittlung",
    "workforce",
)

# Formulierungen in der Stellenbeschreibung, die typisch für Zeitarbeit oder
# Vermittlung im Kundenauftrag sind.
DEFAULT_EXCLUDED_DESCRIPTION_PHRASES: tuple[str, ...] = (
    "im auftrag unseres kunden",
    "fuer unseren kunden",
    "fuer einen unserer kunden",
    "unser kunde ist",
    "arbeitnehmerueberlassung",
    "personalvermittlung",
    "direktvermittlung",
)
# Bewusst nicht enthalten: "zeitarbeit" und "personaldienstleister", weil kleine
# Betriebe oft "keine Zeitarbeit" schreiben, um sich abzugrenzen.


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value is not None else default


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if value is None:
        return list(default)
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class Settings:
    """Laufzeitparameter für einen Scraper-Lauf."""

    location: str = "Salzgitter, Niedersachsen"
    country_indeed: str = "germany"
    radius_km: int = 15
    days: int = 14
    # Leere Liste bedeutet: eine Suche ohne Suchbegriff, also alle Stellen im Umkreis.
    search_terms: list[str] = field(default_factory=list)
    # Obergrenze pro Suchbegriff. Indeed liefert pro Suche ohnehin maximal ca. 1000 Treffer.
    results_wanted: int = 300
    max_employees: int = 20
    match_threshold: int = 90
    fit_city: str = "Salzgitter"
    description_max_chars: int = 600
    excluded_employers: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_EMPLOYERS)
    )
    excluded_name_keywords: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_NAME_KEYWORDS)
    )
    excluded_description_phrases: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_DESCRIPTION_PHRASES)
    )
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    @property
    def radius_miles(self) -> int:
        """JobSpy übergibt den Radius an Indeed in Meilen (radiusUnit: MILES)."""
        miles = self.radius_km / 1.609344
        return max(1, int(miles + 0.999))

    @property
    def hours_old(self) -> int:
        return self.days * 24


def load_settings() -> Settings:
    """Liest Defaults und Umgebungsvariablen (inklusive .env, falls vorhanden)."""
    if load_dotenv is not None:
        load_dotenv()
    defaults = Settings()
    return Settings(
        location=_env("INDEED_LOCATION", defaults.location),
        radius_km=_env_int("INDEED_RADIUS_KM", defaults.radius_km),
        days=_env_int("INDEED_DAYS", defaults.days),
        search_terms=_env_list("INDEED_SEARCH_TERMS", defaults.search_terms),
        results_wanted=_env_int("INDEED_RESULTS_WANTED", defaults.results_wanted),
        max_employees=_env_int("INDEED_MAX_EMPLOYEES", defaults.max_employees),
        match_threshold=_env_int("INDEED_MATCH_THRESHOLD", defaults.match_threshold),
        supabase_url=_env("SUPABASE_URL"),
        supabase_service_role_key=_env("SUPABASE_SERVICE_ROLE_KEY"),
    )
