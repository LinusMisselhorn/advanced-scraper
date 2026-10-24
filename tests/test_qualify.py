import pytest

from scraper.qualify import (
    employees_estimate,
    is_excluded_employer,
    parse_employee_label,
    qualify_job,
)


@pytest.mark.parametrize(
    "name",
    [
        "Salzgitter AG",
        "Salzgitter Flachstahl GmbH",
        "Volkswagen AG",
        "Robert Bosch GmbH",
        "MAN Truck & Bus SE",
        "Alstom Transport Deutschland GmbH",
        "Randstad Deutschland GmbH & Co. KG",
        "Adecco Personaldienstleistungen GmbH",
        "Persona service AG & Co. KG",
        "Beispiel Personalservice Nord GmbH",
        "Muster Zeitarbeit GmbH",
        "Nord Recruiting Partner",
    ],
)
def test_excluded_employers(name, settings):
    assert is_excluded_employer(name, settings) is not None


@pytest.mark.parametrize(
    "name",
    [
        "Autohaus Salzgitter GmbH",  # "Salzgitter" allein ist kein Ausschluss
        "Hermann Bäckerei",  # "man" steckt im Wort, ist aber kein eigenes Token
        "Bäckerei Krause",
        "Friseursalon Haarmonie",
        "Elektro Beispielmann e.K.",
    ],
)
def test_small_businesses_pass(name, settings):
    assert is_excluded_employer(name, settings) is None


def test_missing_name_is_excluded(settings):
    assert is_excluded_employer(None, settings) == "kein Firmenname"
    assert is_excluded_employer("   ", settings) == "kein Firmenname"


def test_exclusion_list_is_configurable(settings):
    settings.excluded_employers.append("Bäckerei Krause")
    assert is_excluded_employer("Bäckerei Krause GmbH", settings) is not None


@pytest.mark.parametrize(
    "label, expected",
    [
        ("2 bis 10", (2, 10)),
        ("11 bis 50", (11, 50)),
        ("51 bis 200", (51, 200)),
        ("10.001+", (10001, None)),
        ("Mehr als 10.000", (10000, None)),
        ("bis 10", (1, 10)),
        ("5", (5, 5)),
        (None, (None, None)),
        ("", (None, None)),
        ("unbekannt", (None, None)),
    ],
)
def test_parse_employee_label(label, expected):
    assert parse_employee_label(label) == expected


def test_employees_estimate():
    assert employees_estimate("2 bis 10") == 10
    assert employees_estimate("10.001+") == 10001
    assert employees_estimate(None) is None


def test_qualify_size_limit(settings):
    job = {"company": "Beispiel Großhandel", "company_num_employees": "51 bis 200"}
    assert not qualify_job(job, settings).ok
    settings.max_employees = 100
    assert qualify_job(job, settings).ok


def test_qualify_range_overlapping_limit_passes(settings):
    # Untergrenze 11 liegt unter 20, die Firma kann also klein sein
    assert qualify_job({"company": "Elektro X", "company_num_employees": "11 bis 50"}, settings).ok


def test_qualify_staffing_description(settings):
    job = {"company": "Tischlerei Holzwerk", "description": "Im Auftrag unseres Kunden suchen wir"}
    verdict = qualify_job(job, settings)
    assert not verdict.ok and "Personaldienstleister" in verdict.reason


def test_keine_zeitarbeit_is_not_excluded(settings):
    job = {"company": "Bäckerei Krause", "description": "Keine Zeitarbeit, direkte Festanstellung."}
    assert qualify_job(job, settings).ok
