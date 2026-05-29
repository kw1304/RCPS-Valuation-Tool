"""레코드 중복제거(dedup) — 결합 스캔(여러 회신본을 한 PDF로 합본)과 개별 회신본이
동시에 입력될 때 동일 holding 이 두 번 집계되는 이중계상을 막는다.

코스맥스 FY2024 사례: 'new-document...pdf' 가 모든 개별 BC-N 온라인 회신을 합본한
스캔이라, 같은 금융자산이 개별파일+합본 두 번 파싱돼 AC1 합계가 ~2배가 됐다.

dedup_key 는 (ac_section, account_no, product, balance, currency) 를 키로 만든다.
bank/bc_no 는 키에서 제외(합본 스캔은 bc_no·bank 가 비어있음). 잔액 0 은 키 충돌이
흔해 dedup 대상에서 제외(None 반환 → 항상 보존)."""
from decimal import Decimal

from src.domain.record_dedup import dedup_key


def test_same_account_balance_same_key():
    a = dedup_key("AC1", {"account_no": "25700072804088", "balance": "20000000.00",
                          "currency": "KRW", "product": "기업은행 기업자유", "bank": "기업은행"})
    b = dedup_key("AC1", {"account_no": "25700072804088", "balance": "20000000.00",
                          "currency": "KRW", "product": "기업자유", "bank": ""})
    assert a is not None and a == b  # 계좌+잔액 일치 → product/bank 달라도 동일행


def test_accountless_keyed_by_product_balance():
    a = dedup_key("AC1", {"account_no": None, "balance": "3000000.00",
                          "currency": "KRW", "product": "당좌개설보증금", "bank": "기업은행"})
    b = dedup_key("AC1", {"account_no": None, "balance": "3000000.00",
                          "currency": "KRW", "product": "당좌개설보증금", "bank": ""})
    assert a is not None and a == b


def test_distinct_accounts_distinct_keys():
    a = dedup_key("AC1", {"account_no": "111", "balance": "100", "currency": "KRW"})
    b = dedup_key("AC1", {"account_no": "222", "balance": "100", "currency": "KRW"})
    assert a != b


def test_distinct_ac_sections_distinct_keys():
    a = dedup_key("AC1", {"account_no": None, "balance": "100", "currency": "KRW", "product": "x"})
    b = dedup_key("AC5", {"account_no": None, "balance": "100", "currency": "KRW", "product": "x"})
    assert a != b


def test_zero_balance_returns_none():
    # 잔액 0 행은 키 충돌이 흔하므로 dedup 대상에서 제외(None → 항상 보존)
    assert dedup_key("AC1", {"account_no": "a", "balance": "0", "currency": "KRW"}) is None
    assert dedup_key("AC1", {"account_no": "b", "balance": None, "currency": "KRW"}) is None


def test_decimal_and_string_balance_normalize_equal():
    a = dedup_key("AC1", {"account_no": "1", "balance": Decimal("5.00"), "currency": "KRW"})
    b = dedup_key("AC1", {"account_no": "1", "balance": "5", "currency": "KRW"})
    assert a is not None and a == b


# ── dedup_records: tagged 보존 + untagged 결합본 중복만 제거 ──────────────────
def test_distinct_banks_same_amount_both_kept():
    from src.domain.record_dedup import dedup_records
    recs = [
        {"ac_section": "AC2", "bank": "국민은행", "bc_no": "BC-1",
         "payload": {"contract_type": "일반자금대출", "balance": "1200000000",
                     "account_no": None, "currency": "KRW"}},
        {"ac_section": "AC2", "bank": "기업은행", "bc_no": "BC-2",
         "payload": {"contract_type": "일반자금대출", "balance": "1200000000",
                     "account_no": None, "currency": "KRW"}},
    ]
    out = dedup_records(recs)
    assert len(out) == 2, '다른 은행 동일금액 행이 잘못 병합됨'


def test_untagged_duplicate_of_tagged_dropped():
    from src.domain.record_dedup import dedup_records
    recs = [
        {"ac_section": "AC1", "bank": "국민은행", "bc_no": "BC-1",
         "payload": {"product": "보통예금", "account_no": "123",
                     "balance": "500", "currency": "KRW"}},
        {"ac_section": "AC1", "bank": "", "bc_no": "",  # combined-scan copy
         "payload": {"product": "보통예금", "account_no": "123",
                     "balance": "500", "currency": "KRW"}},
    ]
    out = dedup_records(recs)
    assert len(out) == 1 and (out[0].get("bank") or "") != "", \
        'untagged 결합본 중복 미제거 또는 tagged 제거됨'


def test_untagged_unique_kept():
    # untagged 인데 어떤 tagged 와도 안 겹치면 보존(합본만 단독 입력된 경우).
    from src.domain.record_dedup import dedup_records
    recs = [
        {"ac_section": "AC1", "bank": "", "bc_no": "",
         "payload": {"product": "보통예금", "account_no": "999",
                     "balance": "700", "currency": "KRW"}},
    ]
    out = dedup_records(recs)
    assert len(out) == 1


def test_two_untagged_duplicates_collapse_to_one():
    # tagged 가 없고 untagged 끼리 동일 holding 이 두 번이면 한 건만 남긴다.
    from src.domain.record_dedup import dedup_records
    recs = [
        {"ac_section": "AC1", "bank": "", "bc_no": "",
         "payload": {"product": "보통예금", "account_no": "555",
                     "balance": "300", "currency": "KRW"}},
        {"ac_section": "AC1", "bank": "", "bc_no": "",
         "payload": {"product": "보통예금", "account_no": "555",
                     "balance": "300", "currency": "KRW"}},
    ]
    out = dedup_records(recs)
    assert len(out) == 1
