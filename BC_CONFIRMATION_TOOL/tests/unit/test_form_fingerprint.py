from pathlib import Path
from src.infrastructure.pdf.form_fingerprint import identify_form

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"

def _txt(name): return (FIX / name).read_text(encoding="utf-8")

def test_bank_form():
    assert identify_form(_txt("bank.txt")) == "bank"

def test_securities_form():
    assert identify_form(_txt("securities.txt")) == "securities"

def test_insurance_form():
    assert identify_form(_txt("insurance.txt")) == "insurance"

def test_surety_form():
    assert identify_form(_txt("surety.txt")) == "surety"

def test_postal_ocr_unknown():
    assert identify_form(_txt("postal_ocr.txt")) == "unknown"
