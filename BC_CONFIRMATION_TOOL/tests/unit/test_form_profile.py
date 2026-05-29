from src.infrastructure.pdf.form_profile import FormProfile

def test_bank_section2_is_ac2():
    p = FormProfile.load()
    assert p.route("bank", 2)["ac"] == "AC2"

def test_securities_section2_is_detail():
    p = FormProfile.load()
    assert p.route("securities", 2)["ac"] == "AC1_DETAIL"

def test_insurance_section1_is_ac7():
    p = FormProfile.load()
    assert p.route("insurance", 1)["ac"] == "AC7"

def test_provided_direction_marked():
    p = FormProfile.load()
    assert p.route("bank", 5)["direction"] == "provided"

def test_unknown_section_returns_none():
    p = FormProfile.load()
    assert p.route("bank", 99) is None
