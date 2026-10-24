"""Firmen-Abgleich: Namensnormalisierung und Fuzzy-Matching gegen public.companies.

Ablauf pro Stellenanzeige:
1. Domain-Treffer: Liefert Indeed eine Firmenwebsite und existiert dieselbe
   Domain bereits in companies, ist das der stärkste Treffer.
2. Exakter Treffer auf dem normalisierten Namen.
3. Fuzzy-Treffer (rapidfuzz token_sort_ratio) oberhalb eines Schwellwerts.
   Sind bei beiden Datensätzen Orte bekannt und verschieden, zählt nur ein
   Score von 100, damit gleichnamige Betriebe in anderen Städten nicht
   zusammengelegt werden.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from rapidfuzz import fuzz, process

_UMLAUTS = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "é": "e",
        "è": "e",
        "á": "a",
        "à": "a",
        "ó": "o",
        "ç": "c",
    }
)

# Rechtsformen mit Punkten, die vor dem Entfernen der Satzzeichen behandelt
# werden müssen (sonst bleiben einzelne Buchstaben wie "e" und "k" übrig).
_DOTTED_LEGAL_FORMS = re.compile(
    r"\be\s*\.\s*(?:kfm|kfr|k|v|g)\b\s*\.?"  # e.K., e.Kfm., e.Kfr., e.V., e.G.
    r"|\bgmbh\s*&\s*co\.?\s*kg(?:aa)?\b"  # GmbH & Co. KG / KGaA
    r"|\bug\s*\(\s*haftungsbeschraenkt\s*\)"  # UG (haftungsbeschränkt)
    r"|\bpart\s*g\s*mbb\b"
)

# Alles ab "Inh." bzw. "Inhaber(in)" ist Zusatz zum Inhaber und kein Firmenname.
_OWNER_SUFFIX = re.compile(r"\binh(?:aber(?:in)?)?\b\.?.*$")

# Einzelne Tokens, die als Rechtsform oder Füllwort gelten.
LEGAL_FORM_TOKENS: frozenset[str] = frozenset(
    {
        "gmbh",
        "mbh",
        "ggmbh",
        "ag",
        "kg",
        "kgaa",
        "ohg",
        "gbr",
        "ug",
        "haftungsbeschraenkt",
        "ek",
        "ev",
        "eg",
        "se",
        "co",
        "partg",
        "partgmbb",
        "ltd",
        "inc",
        "llc",
        "gesellschaft",
        "buergerlichen",
        "rechts",
        "mit",
        "beschraenkter",
        "haftung",
    }
)


def fold_text(text: str | None) -> str:
    """Kleinschreibung, Unicode-Normalisierung, Umlaute als ae/oe/ue/ss."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).lower().translate(_UMLAUTS)
    # Verbleibende diakritische Zeichen entfernen
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def normalize_company_name(name: str | None) -> str:
    """Normalisiert einen Firmennamen für den Abgleich.

    Beispiel: "Bäckerei Müller GmbH & Co. KG" wird zu "baeckerei mueller".
    """
    text = fold_text(name)
    if not text:
        return ""
    text = _OWNER_SUFFIX.sub(" ", text)
    text = _DOTTED_LEGAL_FORMS.sub(" ", text)
    text = text.replace("&", " ").replace("+", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in LEGAL_FORM_TOKENS]
    return " ".join(tokens)


def normalize_city(city: str | None) -> str:
    """Ort normalisieren, Stadtteilzusätze wie "Salzgitter-Bad" bleiben erhalten."""
    return re.sub(r"[^a-z0-9]+", " ", fold_text(city)).strip()


def same_city(a: str | None, b: str | None) -> bool:
    """True, wenn ein Ort Präfix des anderen ist (Salzgitter und Salzgitter Bad)."""
    na, nb = normalize_city(a), normalize_city(b)
    if not na or not nb:
        return False
    return na.startswith(nb) or nb.startswith(na)


def extract_domain(url: str | None) -> str | None:
    """Domain ohne www. aus einer URL, z. B. "https://www.beispiel.de/x" zu "beispiel.de"."""
    if not url:
        return None
    url = str(url).strip()
    if "://" not in url:
        url = "https://" + url
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


@dataclass
class CompanyRecord:
    """Minimale Sicht auf einen Datensatz aus public.companies."""

    id: str
    name: str
    city: str | None = None
    domain: str | None = None
    normalized: str = ""

    def __post_init__(self) -> None:
        if not self.normalized:
            self.normalized = normalize_company_name(self.name)


@dataclass
class MatchResult:
    company: CompanyRecord
    method: str  # "domain", "exact" oder "fuzzy"
    score: float


@dataclass
class CompanyIndex:
    """In-Memory-Index der bekannten Firmen für den Abgleich eines Laufs."""

    threshold: int = 90
    records: list[CompanyRecord] = field(default_factory=list)

    def add(self, record: CompanyRecord) -> None:
        self.records.append(record)

    def match(
        self, name: str | None, city: str | None = None, website: str | None = None
    ) -> MatchResult | None:
        domain = extract_domain(website)
        if domain:
            for rec in self.records:
                if rec.domain and rec.domain == domain:
                    return MatchResult(rec, "domain", 100.0)

        normalized = normalize_company_name(name)
        if not normalized:
            return None

        exact = [r for r in self.records if r.normalized == normalized]
        if exact:
            # Bei mehreren gleichnamigen Firmen die mit passendem Ort bevorzugen
            exact.sort(key=lambda r: not same_city(r.city, city))
            return MatchResult(exact[0], "exact", 100.0)

        candidates = [r for r in self.records if r.normalized]
        if not candidates:
            return None
        hits = process.extract(
            normalized,
            [r.normalized for r in candidates],
            scorer=fuzz.token_sort_ratio,
            score_cutoff=self.threshold,
            limit=5,
        )
        for _, score, idx in hits:
            rec = candidates[idx]
            cities_known = bool(normalize_city(rec.city)) and bool(normalize_city(city))
            if cities_known and not same_city(rec.city, city) and score < 100:
                continue
            return MatchResult(rec, "fuzzy", float(score))
        return None
