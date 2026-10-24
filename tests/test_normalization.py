import pytest

from scraper.matching import extract_domain, fold_text, normalize_city, normalize_company_name, same_city


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Bäckerei Müller GmbH & Co. KG", "baeckerei mueller"),
        ("Bäckerei Müller GmbH & Co KG", "baeckerei mueller"),
        ("BÄCKEREI MÜLLER", "baeckerei mueller"),
        ("Baeckerei Mueller", "baeckerei mueller"),
        ("Elektro Krause e.K.", "elektro krause"),
        ("Elektro Krause e. K.", "elektro krause"),
        ("Tischlerei Weiß e.Kfm.", "tischlerei weiss"),
        ("Schröder & Söhne GbR", "schroeder soehne"),
        ("Muster UG (haftungsbeschränkt)", "muster"),
        ("Muster gGmbH", "muster"),
        ("Friseur Schmidt Inh. Petra Schmidt", "friseur schmidt"),
        ("Friseur Schmidt Inhaberin Petra Schmidt", "friseur schmidt"),
        ("Sportverein Lebenstedt e.V.", "sportverein lebenstedt"),
        ("  Café  Crème  ", "cafe creme"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_company_name(raw, expected):
    assert normalize_company_name(raw) == expected


def test_fold_text_umlauts():
    assert fold_text("Größe Übung Ärger") == "groesse uebung aerger"


def test_inhouse_is_not_owner_suffix():
    assert normalize_company_name("Inhouse Catering GmbH") == "inhouse catering"


def test_city_helpers():
    assert normalize_city("Salzgitter-Bad") == "salzgitter bad"
    assert same_city("Salzgitter", "Salzgitter-Bad")
    assert same_city("salzgitter bad", "Salzgitter")
    assert not same_city("Wolfenbüttel", "Salzgitter")
    assert not same_city(None, "Salzgitter")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.beispiel.de/karriere", "beispiel.de"),
        ("beispiel.de", "beispiel.de"),
        ("http://Shop.Beispiel.de", "shop.beispiel.de"),
        (None, None),
        ("", None),
    ],
)
def test_extract_domain(url, expected):
    assert extract_domain(url) == expected
