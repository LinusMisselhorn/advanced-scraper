"""Ende-zu-Ende-Test der Planung und des Schreibens mit Fixture und Fake-Client, ohne Netzwerk."""

from scraper.config import SIGNAL_TYPE_INDEED
from scraper.indeed_jobspy import (
    build_plan,
    dataframe_to_records,
    load_fixture,
    main,
    parse_city,
    persist,
    to_iso_date,
)
from scraper.matching import CompanyIndex, CompanyRecord


class FakeClient:
    def __init__(self):
        self.companies = []
        self.signals = {}

    def insert_company(self, company):
        row = {"id": f"uuid-{len(self.companies) + 1}", **company}
        self.companies.append(row)
        return row

    def insert_signals(self, signals):
        new = 0
        for s in signals:
            key = (s["company_id"], s["signal_type_id"], s["url"])
            if key not in self.signals:
                self.signals[key] = s
                new += 1
        return new


def plan_from_fixture(fixture_path, settings, index=None):
    records = dataframe_to_records(load_fixture(fixture_path))
    return build_plan(records, settings, index or CompanyIndex(threshold=settings.match_threshold))


def test_fixture_plan(fixture_path, settings):
    plan = plan_from_fixture(fixture_path, settings)
    firms = {p.job["company"] for p in plan.planned}
    assert "Salzgitter Flachstahl GmbH" not in firms
    assert "Volkswagen AG" not in firms
    assert "Randstad Deutschland GmbH & Co. KG" not in firms
    # Zwei Anzeigen der Bäckerei Krause, aber nur eine neue Firma; Duplikat-URL entfällt
    assert len(plan.planned) == 5
    assert len(plan.new_companies) == 4
    names = {c["name"]: c for c in plan.new_companies.values()}
    assert names["Elektro Beispielmann e.K."]["is_fit"] is False
    assert names["Beispiel Bäckerei Krause GmbH"]["is_fit"] is True
    assert all(c["source"] == "indeed" for c in names.values())


def test_signal_shape(fixture_path, settings):
    plan = plan_from_fixture(fixture_path, settings)
    sig = plan.planned[0].signal
    assert sig["signal_type_id"] == SIGNAL_TYPE_INDEED == 1003
    assert sig["source"] == "indeed"
    assert sig["url"].startswith("https://de.indeed.com/viewjob?jk=")
    assert sig["detected_at"].startswith("2026-10-")
    assert set(sig["raw"]) >= {"title", "location", "date_posted", "description"}
    assert len(sig["raw"]["description"]) <= settings.description_max_chars


def test_existing_company_gets_signal(fixture_path, settings):
    index = CompanyIndex(threshold=settings.match_threshold)
    index.add(CompanyRecord(id="bestand-1", name="Beispiel Baeckerei Krause e.K.", city="Salzgitter-Bad"))
    plan = plan_from_fixture(fixture_path, settings, index)
    krause = [p for p in plan.planned if "Krause" in p.job["company"]]
    assert len(krause) == 2
    assert all(p.company_key == "bestand-1" for p in krause)
    assert len(plan.new_companies) == 3


def test_persist_is_idempotent(fixture_path, settings):
    client = FakeClient()
    stats1 = persist(plan_from_fixture(fixture_path, settings), client)
    assert stats1["neue_firmen"] == 4 and stats1["signale_neu"] == 5

    # Zweiter Lauf: Bestand inklusive der eben angelegten Firmen laden
    index = CompanyIndex(threshold=settings.match_threshold)
    for row in client.companies:
        index.add(CompanyRecord(id=row["id"], name=row["name"], city=row.get("city"), domain=row.get("domain")))
    stats2 = persist(plan_from_fixture(fixture_path, settings, index), client)
    assert stats2["neue_firmen"] == 0
    assert stats2["signale_neu"] == 0
    assert stats2["signale_duplikat"] == 5


def test_helpers():
    assert parse_city("Salzgitter, NI, DE") == "Salzgitter"
    assert parse_city(None) is None
    assert to_iso_date("2026-10-20") == "2026-10-20T00:00:00+00:00"
    assert to_iso_date(None) is None
    assert to_iso_date("kein datum") is None


def test_cli_dry_run_with_fixture(fixture_path, capsys, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr("scraper.config.load_dotenv", None)
    rc = main(["--dry-run", "--fixture", str(fixture_path), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"qualifiziert"' in out and "Beispiel Bäckerei Krause" in out


def test_write_mode_requires_credentials(fixture_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr("scraper.config.load_dotenv", None)
    assert main(["--fixture", str(fixture_path)]) == 1
