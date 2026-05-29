"""참고조서(정답) ↔ 툴 파싱결과 비교 하니스 (지속적 매핑 개선용).

목적
----
사람이 완성한 참고조서(4150 AC 금융기관 조회 …xlsx)의 AC 시트 값과,
툴이 회신본 PDF 들을 파싱해 만든 레코드를 **AC별 금액 집합**으로 비교한다.
컬럼 미세정합이 아니라 "정답의 금액이 툴 출력에 들어왔는가 / 툴이 헛것을
만들었는가"를 빠르게 본다 — 매핑 개선의 회귀 가드.

비교 대상 금액(AC별)
  AC1 : 금액(balance)
  AC2 : 한도금액(limit_amt) + 대출금액(balance)  ← POSITIONAL 두 컬럼 모두
  AC4 : 한도금액 + 실행금액(balance)
  AC5 : 장부가(book_amount)  [+ 감정금액(appraised_amount) 있으면]
  AC7 : 부보금액(coverage_amount)

사용
----
  python tools/compare_to_reference.py \
      "INPUT/4150_AC 금융기관 조회_코스맥스비티아이_FY2025_V1.xlsx" \
      "INPUT/온라인"

출력
----
  AC별 MISSED(정답엔 있는데 툴엔 없음) / EXTRA(툴엔 있는데 정답엔 없음) 목록 +
  per-AC 요약(#정답행, #matched, #missed, #extra).

견고성
------
  - 금액은 정수 원화(소수 절사, 콤마 제거)로 정규화해 비교(멀티셋).
  - 0 은 noise 가 많아 비교에서 제외(매칭/미스 판정 대상 아님).
  - 참고시트 헤더 행을 자동 탐색해 금액 컬럼 인덱스를 잡는다(레이아웃 변동 견고).
"""
from __future__ import annotations

import sys
import glob
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openpyxl  # noqa: E402

from src.infrastructure.pdf.extractor import extract_rows  # noqa: E402
from src.infrastructure.pdf.form_fingerprint import identify_form  # noqa: E402
from src.infrastructure.pdf.section_splitter import split_sections  # noqa: E402
from src.infrastructure.pdf.filename_parser import parse_filename  # noqa: E402
from src.application.parse_response_uc import route_or_classify, _dispatch  # noqa: E402


# ── 금액 정규화 ────────────────────────────────────────────────────────────
def _to_int_amount(v) -> int | None:
    """셀/문자열을 정수 원화 금액으로. 비금액·0·None → None.

    '126,598,004.00(126,645,985.00)' 같은 합성 셀은 첫 금액만 취한다."""
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            iv = int(Decimal(str(v)))
        except (InvalidOperation, ValueError):
            return None
        return iv if iv != 0 else None
    s = str(v).strip()
    if not s:
        return None
    # 괄호 안 보조금액 제거(평가액/직전잔액 등)
    s = re.split(r"[(（]", s, maxsplit=1)[0].strip()
    s = s.replace(",", "")
    m = re.match(r"-?\d+(?:\.\d+)?$", s)
    if not m:
        return None
    try:
        iv = int(Decimal(s))
    except (InvalidOperation, ValueError):
        return None
    return iv if iv != 0 else None


# ── 참고조서 읽기 ──────────────────────────────────────────────────────────
# 시트 prefix → (라벨, [비교할 헤더명들])
_REF_SHEETS = {
    "AC1": ("금융자산", ["금액"]),
    "AC2": ("차입금", ["한도금액", "대출금액"]),
    # ① 회사가 제공받은(한도액/실행금액) + ② 회사가 타인에게 제공한 연대보증.
    # 이 시트는 통화/금액 2단 stacked 구조라 단일 헤더행 모델로 금액컬럼을 못 잡는다.
    # → AC4 는 헤더 무관하게 모든 데이터 셀에서 100만↑ 원화 금액을 수집한다(아래 특례).
    "AC4": ("지급보증", []),
    "AC5": ("담보제공자산", ["장부가", "장부금액", "감정금액", "설정금액", "담보금액"]),
    "AC7": ("보험가입내역", ["부보금액"]),
}


def _find_sheet(wb, prefix: str):
    for name in wb.sheetnames:
        # 'AC2. 차입금' / 'AC2.차입금' 등 — prefix 가 'AC2' 면 'AC2.' 로 시작
        head = name.replace(" ", "")
        if head.startswith(prefix + ".") or head.startswith(prefix + "."):
            return wb[name]
    return None


def _header_amount_cols(ws, header_names: list[str]) -> tuple[int, list[int]]:
    """헤더 행 번호와, header_names 중 하나와 일치하는 금액 컬럼 인덱스 목록을 찾는다.

    헤더가 2줄에 걸쳐(병합) 있을 수 있어 앞 30행을 스캔, 가장 많은 매칭을 가진 행 채택.
    반환: (data_start_row, [col_idx, ...]). 못 찾으면 (0, [])."""
    best_row, best_cols = 0, []
    wanted = [h.replace(" ", "") for h in header_names]
    for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=30, values_only=True), 1):
        cols = []
        for ci, cell in enumerate(row):
            if cell is None:
                continue
            txt = str(cell).replace(" ", "")
            if any(w and w in txt for w in wanted):
                cols.append(ci)
        if len(cols) > len(best_cols):
            best_row, best_cols = ri, cols
    return best_row, best_cols


# AC4 등 stacked 시트는 헤더 매핑 대신 전체 금액 스캔. 100만 미만(증권번호 index·
# 순위 등)은 잡지 않는다.
_MIN_REF_AMOUNT = 1_000_000


def _scan_amounts_min(ws, minv: int) -> Counter:
    """시트 전체 데이터 셀에서 minv 이상 원화 금액을 멀티셋으로 수집."""
    amounts: Counter = Counter()
    for row in ws.iter_rows(values_only=True):
        for cell in row:
            iv = _to_int_amount(cell)
            if iv is not None and iv >= minv:
                amounts[iv] += 1
    return amounts


def read_reference_amounts(xlsx: Path) -> dict[str, Counter]:
    """참고조서 → {AC: Counter(정수금액)}. 0/비금액 제외."""
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    out: dict[str, Counter] = {}
    for ac, (label, headers) in _REF_SHEETS.items():
        ws = _find_sheet(wb, ac)
        if ws is None:
            out[ac] = Counter()
            continue
        # AC4 특례: 통화/금액 2단 stacked + ①② 2개 표 → 헤더 컬럼 매핑이 불안정.
        # 시트 전체 데이터 셀에서 100만↑ 원화 금액을 수집(지급보증 시트는 금액 전용).
        if ac == "AC4":
            out[ac] = _scan_amounts_min(ws, _MIN_REF_AMOUNT)
            continue
        hdr_row, cols = _header_amount_cols(ws, headers)
        amounts: Counter = Counter()
        if cols:
            for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
                for ci in cols:
                    if ci < len(row):
                        iv = _to_int_amount(row[ci])
                        if iv is not None:
                            amounts[iv] += 1
        out[ac] = amounts
    return out


# ── 툴 파싱 ────────────────────────────────────────────────────────────────
# 레코드(payload dict) → 비교할 금액 필드(AC별)
_TOOL_FIELDS = {
    "AC1": ["balance"],
    "AC2": ["limit_amt", "balance"],
    "AC4": ["limit_amt", "balance"],
    "AC5": ["book_amount", "appraised_amount"],
    "AC7": ["coverage_amount"],
}


def parse_pdf_dir(pdf_dir: Path) -> dict[str, Counter]:
    """회신본 PDF 디렉터리 → {AC: Counter(정수금액)} (툴 파싱 결과)."""
    out: dict[str, Counter] = {ac: Counter() for ac in _TOOL_FIELDS}
    pdfs = sorted(glob.glob(str(pdf_dir / "*.pdf")))
    for p in pdfs:
        path = Path(p)
        meta = parse_filename(path.name)
        bc_no = meta.get("bc_no") or ""
        bank = meta.get("bank_raw") or ""
        try:
            text = extract_rows(path)
        except Exception as e:
            print(f"  [WARN] extract 실패 {path.name}: {e}", file=sys.stderr)
            continue
        family = identify_form(text)
        if family == "unknown":
            continue
        blocks = split_sections(text)
        for section_no, block in blocks.items():
            route = route_or_classify(family, section_no, block)
            if not route:
                continue
            ac = route["ac"]
            store_ac = "AC1" if ac == "AC1_DETAIL" else ac
            if store_ac not in _TOOL_FIELDS:
                continue
            parse_block = route.get("block", block)
            try:
                recs = _dispatch(ac, parse_block, bc_no, bank, route)
            except Exception:
                continue
            for rec in recs:
                d = rec.model_dump() if hasattr(rec, "model_dump") else dict(rec)
                for fld in _TOOL_FIELDS[store_ac]:
                    iv = _to_int_amount(d.get(fld))
                    if iv is not None:
                        out[store_ac][iv] += 1
    return out


# ── 비교 ───────────────────────────────────────────────────────────────────
def _fmt(n: int) -> str:
    return f"{n:,}"


def compare(ref: dict[str, Counter], tool: dict[str, Counter]) -> None:
    acs = ["AC1", "AC2", "AC4", "AC5", "AC7"]
    print("=" * 72)
    print("참고조서(정답) ↔ 툴 파싱 금액집합 비교  (0·비금액 제외)")
    print("=" * 72)
    summary = []
    for ac in acs:
        r = ref.get(ac, Counter())
        t = tool.get(ac, Counter())
        # 멀티셋 차집합
        missed = r - t   # 정답엔 있는데 툴엔 부족
        extra = t - r    # 툴엔 있는데 정답엔 없음
        matched_multiset = (r & t)
        n_ref = sum(r.values())
        n_matched = sum(matched_multiset.values())
        n_missed = sum(missed.values())
        n_extra = sum(extra.values())
        summary.append((ac, n_ref, n_matched, n_missed, n_extra))

        print(f"\n── {ac} ── (정답 {n_ref}건, matched {n_matched}, "
              f"missed {n_missed}, extra {n_extra})")
        if missed:
            print("  MISSED (정답엔 있는데 툴엔 없음):")
            for amt, c in sorted(missed.items(), reverse=True):
                tag = f" x{c}" if c > 1 else ""
                print(f"    - {_fmt(amt)}{tag}")
        if extra:
            print("  EXTRA (툴엔 있는데 정답엔 없음):")
            for amt, c in sorted(extra.items(), reverse=True):
                tag = f" x{c}" if c > 1 else ""
                print(f"    + {_fmt(amt)}{tag}")
        if not missed and not extra:
            print("  (완전 일치)")

    print("\n" + "=" * 72)
    print("요약  AC | #정답 | matched | missed | extra")
    print("-" * 72)
    for ac, n_ref, n_matched, n_missed, n_extra in summary:
        print(f"  {ac:5} | {n_ref:5} | {n_matched:7} | {n_missed:6} | {n_extra:5}")
    print("=" * 72)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        print("사용: python tools/compare_to_reference.py <참고조서.xlsx> <회신본PDF디렉터리>")
        return 2
    xlsx = Path(argv[1])
    pdf_dir = Path(argv[2])
    if not xlsx.exists():
        print(f"참고조서 없음: {xlsx}", file=sys.stderr)
        return 2
    if not pdf_dir.is_dir():
        print(f"PDF 디렉터리 없음: {pdf_dir}", file=sys.stderr)
        return 2
    print(f"참고조서: {xlsx}")
    print(f"회신본  : {pdf_dir}")
    ref = read_reference_amounts(xlsx)
    tool = parse_pdf_dir(pdf_dir)
    compare(ref, tool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
