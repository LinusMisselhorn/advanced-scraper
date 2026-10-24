from scraper.matching import CompanyIndex, CompanyRecord


def make_index(threshold=90):
    index = CompanyIndex(threshold=threshold)
    index.add(CompanyRecord(id="a", name="Bäckerei Krause GmbH", city="Salzgitter"))
    index.add(CompanyRecord(id="b", name="Elektro Beispielmann e.K.", city="Wolfenbüttel", domain="beispielmann.de"))
    index.add(CompanyRecord(id="c", name="Autohaus Schmidt", city="Braunschweig"))
    index.add(CompanyRecord(id="d", name="Autohaus Schmidt", city="Salzgitter"))
    return index


def test_exact_match_ignores_legal_form_and_umlauts():
    m = make_index().match("Baeckerei Krause", city="Salzgitter")
    assert m is not None and m.company.id == "a" and m.method == "exact"


def test_domain_match_wins():
    m = make_index().match("Ganz anderer Name", city="Salzgitter", website="https://www.beispielmann.de/jobs")
    assert m is not None and m.company.id == "b" and m.method == "domain"


def test_fuzzy_match_small_typo():
    m = make_index().match("Bäckerei Kraus GmbH", city="Salzgitter")
    assert m is not None and m.company.id == "a" and m.method == "fuzzy"
    assert m.score >= 90


def test_fuzzy_respects_threshold():
    # "kranz" gegen "krause" liegt bei ca. 84 und damit unter dem Default 90
    assert make_index().match("Bäckerei Kranz", city="Salzgitter") is None
    assert make_index(threshold=80).match("Bäckerei Kranz", city="Salzgitter").company.id == "a"
    assert make_index(threshold=99).match("Bäckerei Kraus", city="Salzgitter") is None


def test_fuzzy_rejects_different_city():
    # Tippfehler plus anderer Ort: kein Treffer, damit gleichnamige Betriebe getrennt bleiben
    m = make_index().match("Elektro Beispielman", city="Salzgitter")
    assert m is None


def test_exact_match_prefers_same_city():
    m = make_index().match("Autohaus Schmidt GmbH", city="Salzgitter")
    assert m.company.id == "d"


def test_no_match_for_unrelated_name():
    assert make_index().match("Friseursalon Haarmonie", city="Salzgitter") is None


def test_empty_name_never_matches():
    assert make_index().match("", city="Salzgitter") is None
    assert make_index().match(None) is None
