"""Qualifizierung von Stellenanzeigen vor dem Speichern.

Eine Anzeige ist nur dann ein brauchbares Signal, wenn sie von einem kleinen,
inhabergeführten Betrieb stammt. Ausgeschlossen werden:
- Anzeigen ohne Firmennamen
- Großarbeitgeber und Ketten laut Ausschlussliste
- Personaldienstleister (Name oder typische Formulierungen in der Beschreibung)
- Firmen, deren von Indeed gemeldete Mitarbeiterzahl über der Grenze liegt
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Settings
from .matching import fold_text, normalize_company_name


@dataclass
class Verdict:
    ok: bool
    reason: str | None = None


def parse_employee_label(label: str | None) -> tuple[int | None, int | None]:
    """Wandelt Indeed-Labels wie "11 bis 50", "10.001+" oder "Mehr als 10.000" in (min, max).

    Tausenderpunkte und Leerzeichen werden entfernt. Bei offenen Angaben wie
    "10.001+" ist max None.
    """
    if not label:
        return None, None
    text = str(label).strip()
    if not text or text.lower() == "nan":
        return None, None
    # Tausendertrennzeichen (Punkt, Komma, schmales Leerzeichen) zwischen Ziffern entfernen
    text = re.sub(r"(?<=\d)[.,   ](?=\d{3}\b)", "", text)
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        folded = fold_text(text)
        n = numbers[0]
        if "+" in text or "mehr als" in folded or "ueber" in folded:
            return n, None
        if "weniger als" in folded or "unter" in folded or "bis" in folded:
            return 1, n
        return n, n
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def employees_estimate(label: str | None) -> int | None:
    """Schätzwert für companies.employees_est: Obergrenze, sonst Untergrenze."""
    low, high = parse_employee_label(label)
    return high if high is not None else low


def light_normalize(text: str | None) -> str:
    """Wie fold_text, aber Satzzeichen werden zu Leerzeichen und Rechtsformen bleiben.

    Für die Ausschlussliste wichtig: "Salzgitter AG" darf nicht zu "salzgitter"
    schrumpfen, sonst fiele jedes "Autohaus Salzgitter" heraus.
    """
    return re.sub(r"[^a-z0-9]+", " ", fold_text(text)).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """Prüft, ob die Phrase als zusammenhängende Wortfolge im Text vorkommt."""
    needle = light_normalize(phrase)
    if not needle:
        return False
    return re.search(rf"(?:^| ){re.escape(needle)}(?: |$)", haystack) is not None


def is_excluded_employer(name: str | None, settings: Settings) -> str | None:
    """Gibt den Ausschlussgrund zurück oder None."""
    normalized = normalize_company_name(name)
    if not normalized:
        return "kein Firmenname"
    light = light_normalize(name)
    for entry in settings.excluded_employers:
        if _contains_phrase(light, entry):
            return f"Ausschlussliste: {entry}"
    compact = normalized.replace(" ", "")
    for keyword in settings.excluded_name_keywords:
        if fold_text(keyword).replace(" ", "") in compact:
            return f"Name deutet auf Personaldienstleister: {keyword}"
    return None


def is_staffing_description(description: str | None, settings: Settings) -> str | None:
    text = fold_text(description)
    if not text:
        return None
    for phrase in settings.excluded_description_phrases:
        if fold_text(phrase) in text:
            return f"Beschreibung deutet auf Personaldienstleister: {phrase}"
    return None


def qualify_job(job: dict, settings: Settings) -> Verdict:
    """Prüft eine Anzeige (eine Zeile des JobSpy-DataFrames als dict)."""
    reason = is_excluded_employer(job.get("company"), settings)
    if reason:
        return Verdict(False, reason)

    low, _ = parse_employee_label(job.get("company_num_employees"))
    if low is not None and low > settings.max_employees:
        return Verdict(
            False,
            f"zu groß: {job.get('company_num_employees')} Mitarbeiter (Grenze {settings.max_employees})",
        )

    reason = is_staffing_description(job.get("description"), settings)
    if reason:
        return Verdict(False, reason)

    return Verdict(True)
