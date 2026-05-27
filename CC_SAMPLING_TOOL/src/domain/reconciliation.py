"""채권채무조회서 차이 판정 — 장부가 vs 회신 잔액 대사.

ISA 505 / 감사기준서 505에 따라 회신 잔액과 장부가 차이를 수치로 계산하고
허용 차이(tolerance) 내 여부를 판정한다.

v2 확장:
  - declared_match 우선 처리 (PDF 자체 선언 존중)
  - per_account 계정별 원통화 비교
  - UploadGuide 원통화 vs PDF 원통화 직접 비교 (환산 오류 제거)
  - decision_basis 기록 (추후 감사 근거)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReconResult:
    status: str                          # "matched" | "mismatch" | "needs_review" | "extraction_failed"
    difference: Optional[float]         # 장부가 - 회신 잔액 (None이면 추출 실패)
    difference_pct: Optional[float]     # 차이 / 장부가 (분모 0이면 None)
    tolerance: float                     # 적용된 허용 차이
    # ── v2 확장 ────────────────────────────────────────────────────────
    decision_basis: str = "total"
    # "declared" — PDF 자체 일치 선언 기반
    # "per_account" — 계정별 원통화 비교
    # "total" — 합계 금액 비교 (KRW 환산 포함)
    # "fallback" — UploadGuide 없어 KRW 장부가 직접 비교
    difference_currency: str = "KRW"
    per_account_findings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def reconcile(
    ledger_balance: float,
    extracted_balance: Optional[float],
    tolerance: float = 0.0,
) -> ReconResult:
    """장부가와 추출된 회신 잔액을 대사한다 (기존 인터페이스 유지).

    Args:
        ledger_balance: Step 1 샘플링 결과의 장부가
        extracted_balance: PDF에서 추출된 잔액 (None이면 추출 실패)
        tolerance: 차이 허용 금액 (기본 0원 — 1원이라도 다르면 mismatch)

    Returns:
        ReconResult: 상태·차이·차이율 포함
    """
    if extracted_balance is None:
        return ReconResult(
            status="extraction_failed",
            difference=None,
            difference_pct=None,
            tolerance=tolerance,
        )

    difference = ledger_balance - extracted_balance
    difference_pct = (difference / ledger_balance) if ledger_balance != 0 else None

    if abs(difference) <= tolerance:
        status = "matched"
    else:
        status = "mismatch"

    return ReconResult(
        status=status,
        difference=difference,
        difference_pct=difference_pct,
        tolerance=tolerance,
    )


def reconcile_v2(
    ledger_balance_krw: float,
    parsed_reply,            # ParsedReply (Week 5 v2 확장 필드 포함)
    upload_guide_row=None,   # PartyContact | None
    currency_resolver=None,  # CurrencyResolver | None
    tolerance: float = 0.0,
    tolerance_pct: float = 0.0,
) -> ReconResult:
    """v2 대사 — declared > per_account > total > fallback 우선순위.

    Args:
        ledger_balance_krw:  Step 1 장부가 (KRW)
        parsed_reply:        parse_confirmation_v2() 결과
        upload_guide_row:    UploadGuideData.send_targets 에서 찾은 PartyContact
        currency_resolver:   CurrencyResolver 인스턴스
        tolerance:           절대 허용 차이 (KRW)
        tolerance_pct:       상대 허용 차이율 (0.01 = 1%)

    대사 우선순위:
    1. parsed_reply.declared_match == True  → matched
       단 차이 5% 초과 시 needs_review 강등
    2. parsed_reply.declared_match == False → mismatch
    3. per_account_rows 있음 → 계정별 원통화 비교
    4. per_account_rows 없음 → 합계 금액 비교 (currency_resolver 활용)
    5. 추출 실패 → extraction_failed
    """
    notes: list[str] = []
    per_findings: list[dict] = []

    # ── 추출 실패 체크 ─────────────────────────────────────────────────
    if parsed_reply is None:
        return ReconResult(
            status="extraction_failed",
            difference=None,
            difference_pct=None,
            tolerance=tolerance,
            decision_basis="fallback",
            notes=["parsed_reply is None"],
        )

    extracted_bal = parsed_reply.extracted_balance
    orig_currency = getattr(parsed_reply, "original_currency", "KRW")
    declared = getattr(parsed_reply, "declared_match", None)
    per_rows = getattr(parsed_reply, "per_account_rows", [])

    if extracted_bal is None and not per_rows:
        return ReconResult(
            status="extraction_failed",
            difference=None,
            difference_pct=None,
            tolerance=tolerance,
            decision_basis="fallback",
            notes=["금액 추출 실패 — per_account_rows 없음"],
        )

    # ── 유효 tolerance 결정 ───────────────────────────────────────────
    eff_tolerance = tolerance
    if tolerance_pct > 0 and ledger_balance_krw > 0:
        pct_tol = abs(ledger_balance_krw) * tolerance_pct
        eff_tolerance = max(tolerance, pct_tol)

    def _within_tolerance(diff: float) -> bool:
        return abs(diff) <= eff_tolerance

    # ── 1. declared_match 우선 ────────────────────────────────────────
    if declared is True:
        # 수치 검증: 차이 5% 초과이면 신뢰 불가 → needs_review 강등
        plausibility_check = False
        if extracted_bal is not None and ledger_balance_krw != 0:
            # 환산 시도
            compare_bal = extracted_bal
            if orig_currency != "KRW" and currency_resolver is not None:
                converted = currency_resolver.original_to_krw(extracted_bal, orig_currency)
                if converted is not None:
                    compare_bal = converted
            diff = ledger_balance_krw - compare_bal
            diff_pct = abs(diff / ledger_balance_krw)
            plausibility_check = diff_pct > 0.05  # 5% 초과 = 신뢰 불가
            notes.append(f"declared=일치 수치검증: 차이율={diff_pct:.2%}")

        if plausibility_check:
            notes.append("declared=일치 이지만 차이 5% 초과 → needs_review 강등")
            return ReconResult(
                status="needs_review",
                difference=None,
                difference_pct=None,
                tolerance=eff_tolerance,
                decision_basis="declared",
                notes=notes,
            )

        return ReconResult(
            status="matched",
            difference=0.0,
            difference_pct=0.0,
            tolerance=eff_tolerance,
            decision_basis="declared",
            notes=notes,
        )

    if declared is False:
        notes.append("declared=불일치 선언")
        return ReconResult(
            status="mismatch",
            difference=None,
            difference_pct=None,
            tolerance=eff_tolerance,
            decision_basis="declared",
            notes=notes,
        )

    # ── 2. per_account 비교 ───────────────────────────────────────────
    if per_rows:
        # UploadGuide 계정별 원통화 금액 조회
        ug_acct_map: dict[str, tuple[float, str]] = {}  # acct_name → (amount, currency)
        if upload_guide_row is not None:
            for acct_name, cur, amt in upload_guide_row.accounts:
                if acct_name not in ug_acct_map:
                    ug_acct_map[acct_name] = (amt, cur.upper())

        any_mismatch = False
        any_matched = False

        for row in per_rows:
            if row.reply_amount is None:
                continue
            finding: dict = {
                "account": row.account_name,
                "section": row.section,
                "reply_amount": row.reply_amount,
                "reply_currency": row.currency,
                "match_declared": row.declared_match,
            }

            # UploadGuide 기준값 조회
            ug_info = ug_acct_map.get(row.account_name)
            if ug_info:
                ug_amt, ug_cur = ug_info
                finding["ug_amount"] = ug_amt
                finding["ug_currency"] = ug_cur

                # 통화 일치 여부
                if ug_cur == row.currency.upper():
                    diff = ug_amt - row.reply_amount
                    finding["diff"] = diff
                    finding["within_tolerance"] = _within_tolerance(diff)
                    if _within_tolerance(diff):
                        any_matched = True
                    else:
                        any_mismatch = True
                else:
                    # 통화 불일치 — 환산 시도
                    if currency_resolver is not None and row.currency.upper() != "KRW":
                        reply_krw = currency_resolver.original_to_krw(row.reply_amount, row.currency)
                        ug_krw = currency_resolver.original_to_krw(ug_amt, ug_cur) if ug_cur != "KRW" else ug_amt
                        if reply_krw is not None and ug_krw is not None:
                            diff = ug_krw - reply_krw
                            finding["diff_krw"] = diff
                            finding["within_tolerance"] = _within_tolerance(diff)
                            if _within_tolerance(diff):
                                any_matched = True
                            else:
                                any_mismatch = True
                        else:
                            finding["note"] = "환산 불가"
                    else:
                        finding["note"] = f"통화 불일치: ug={ug_cur}, reply={row.currency}"

            per_findings.append(finding)

        if per_findings:
            if any_mismatch:
                status = "mismatch"
            elif any_matched:
                status = "matched"
            else:
                status = "needs_review"
            notes.append(f"per_account 비교: {len(per_findings)}건")
            return ReconResult(
                status=status,
                difference=None,
                difference_pct=None,
                tolerance=eff_tolerance,
                decision_basis="per_account",
                per_account_findings=per_findings,
                notes=notes,
            )

    # ── 3. 합계 비교 ──────────────────────────────────────────────────
    if extracted_bal is not None:
        # 원통화 직접 비교 (UploadGuide 원통화 사용)
        if upload_guide_row is not None and orig_currency != "KRW":
            orig_info = None
            if currency_resolver is not None:
                orig_info = currency_resolver.get_party_amount_in_original(upload_guide_row.name)
            if orig_info and orig_info[1].upper() == orig_currency.upper():
                ug_orig_amt, _ = orig_info
                diff_orig = ug_orig_amt - extracted_bal
                diff_pct = diff_orig / ug_orig_amt if ug_orig_amt != 0 else None
                status = "matched" if _within_tolerance(diff_orig) else "mismatch"
                notes.append(f"원통화 비교: ug={ug_orig_amt} {orig_currency}, reply={extracted_bal}")
                return ReconResult(
                    status=status,
                    difference=diff_orig,
                    difference_pct=diff_pct,
                    tolerance=eff_tolerance,
                    decision_basis="total",
                    difference_currency=orig_currency,
                    notes=notes,
                )

        # KRW 환산 비교
        compare_bal = extracted_bal
        diff_currency = orig_currency

        if orig_currency != "KRW" and currency_resolver is not None:
            converted = currency_resolver.original_to_krw(extracted_bal, orig_currency)
            if converted is not None:
                compare_bal = converted
                diff_currency = "KRW"
                notes.append(f"환산: {extracted_bal} {orig_currency} → {converted:.0f} KRW")
            else:
                notes.append(f"환산 실패: {orig_currency} → KRW, fallback 직접 비교")

        difference = ledger_balance_krw - compare_bal
        difference_pct = difference / ledger_balance_krw if ledger_balance_krw != 0 else None
        status = "matched" if _within_tolerance(difference) else "mismatch"

        return ReconResult(
            status=status,
            difference=difference,
            difference_pct=difference_pct,
            tolerance=eff_tolerance,
            decision_basis="total",
            difference_currency=diff_currency,
            notes=notes,
        )

    # ── 4. UploadGuide 없고 추출 실패 ─────────────────────────────────
    notes.append("장부가 대비 추출 잔액 없음 — fallback")
    return ReconResult(
        status="extraction_failed",
        difference=None,
        difference_pct=None,
        tolerance=eff_tolerance,
        decision_basis="fallback",
        notes=notes,
    )
