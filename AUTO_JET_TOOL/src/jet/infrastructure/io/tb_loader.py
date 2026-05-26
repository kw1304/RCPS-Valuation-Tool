"""합계잔액시산표(TB) 로더.

합계잔액시산표.xlsx 파일에서 기초잔액·당기차변·당기대변·기말잔액을 적재한다.
특정 회사 시트명에 의존하지 않고 날짜 패턴 또는 "기초"/"기말" 키워드로 자동 감지한다.

지원 양식:
    1. 분할헤더 단일시트 양식 — R0=헤더, R1~=데이터.
       R0에 기초잔액 컬럼("기조찬액"·"기초잔액" 등)과 차대변 누계 컬럼이 있는 단일헤더.
       예: [과목, 기조찬액, 잔액, 차변누계, 차변당월, 대변당월, 대변누계, 잔액, ...]
    2. 멀티헤더 양식 — 단일 시트, R1·R2 두 행이 헤더.
       R1="차변"/R2="잔액" 조합으로 컬럼명을 결합한다.

헤더 기반 동적 매핑을 사용하여 회사별 컬럼명 변형에 자동 대응한다.
부호 결정 우선순위: COA 계정유형(B/P) > 계정코드 첫자리 fallback.

A03_TBRollforward 룰에서 GL 합계와 TB 차변/대변 누계를 비교한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from jet.infrastructure.io.coa_loader import AccountMaster

logger = logging.getLogger(__name__)

# 계정코드 추출 정규식 (앞 공백 + 코드 + 공백 + 명칭)
_ACCT_CODE_RE = re.compile(r"^\s*(\d+)\s+(.+)$")

# ── 헤더 키워드 매핑 ──────────────────────────────────────────────────────────
# 각 표준 필드에 해당하는 한글 키워드 목록 (부분 매칭).
# 새로운 회사 양식을 지원하려면 키워드 목록만 확장하면 된다.
#
# closing_dr / closing_cr 분리 이유:
#   BTI 양식처럼 "잔액"이 두 컬럼으로 나뉘는 경우:
#     col[N]   = 차변잔액 (자산이면 채워짐, 부채·자본이면 0)
#     col[N+5] = 대변잔액 (부채·자본이면 채워짐, 자산이면 0)
#   두 값을 합산해야 실제 기말잔액을 구할 수 있다.
#   명시적 "기말잔액" 컬럼이 있는 경우 closing_single로 감지한다.
_HEADER_KEYWORDS: dict[str, list[str]] = {
    "opening":        ["기조찬액", "기초잔액", "전기이월", "이월잔액", "전기말", "기초"],
    "closing_single": ["기말잔액", "기말", "당기말"],   # 단일 기말잔액 컬럼
    "closing_split":  ["잔액"],                          # 분할 기말잔액 (차변/대변)
    "period_debit":   ["차변누계", "차변계", "차변합계", "차변발생"],
    "period_credit":  ["대변누계", "대변계", "대변합계", "대변발생"],
}

# ── 계정코드 첫자리 부호 테이블 (COA 미제공 fallback) ──────────────────────────
# +1 = 차변잔액 계정 (자산·명세), -1 = 대변잔액 계정 (부채·자본·손익)
_SIGN_BY_PREFIX: dict[str, int] = {
    "1": +1,   # 자산
    "9": +1,   # 명세·비망
    "2": -1,   # 부채
    "3": -1,   # 자본
    "4": -1,   # 매출(수익)
    "5": -1,   # 매출원가(비용)
    "6": -1,   # 판관비(비용)
    "7": -1,   # 기타손익
    "8": -1,   # 금융손익
}


@dataclass(frozen=True)
class TrialBalance:
    """합계잔액시산표 단일 계정 레코드.

    Attributes:
        account_code: 계정코드 (공백·접두어 제거)
        account_name: 계정과목명
        opening_balance: 기초잔액 (기초 이월, 없으면 0)
        period_debit: 당기 차변 합계
        period_credit: 당기 대변 합계
        closing_balance: 기말잔액 (기말 잔액; 차변 또는 대변 중 실잔액)
        opening_dr: 기초 차변 이월 (멀티헤더 양식, 없으면 0)
        opening_cr: 기초 대변 이월 (멀티헤더 양식, 없으면 0)
        closing_dr: 기말 차변 잔액 (멀티헤더 양식, 없으면 0)
        closing_cr: 기말 대변 잔액 (멀티헤더 양식, 없으면 0)
    """

    account_code: str
    account_name: str
    opening_balance: float
    period_debit: float
    period_credit: float
    closing_balance: float
    opening_dr: float = 0.0
    opening_cr: float = 0.0
    closing_dr: float = 0.0
    closing_cr: float = 0.0


class TbLoader:
    """합계잔액시산표 엑셀 파일을 적재하는 로더.

    COA 마스터를 주입하면 계정유형(B/P)을 부호 결정에 활용한다.
    미주입 시 계정코드 첫자리로 fallback한다.

    사용법:
        loader = TbLoader(coa_master=coa)
        tb = loader.load(Path('INPUT/extracted/합계잔액시산표.xlsx'))
        rec = tb['11101010']  # TrialBalance
    """

    def __init__(
        self,
        coa_master: "dict[str, AccountMaster] | None" = None,
    ) -> None:
        """초기화.

        Args:
            coa_master: COA 계정과목 마스터. 계정유형(B/P) 기반 부호 결정에 사용.
                        None이면 계정코드 첫자리로 fallback.
        """
        self._coa = coa_master or {}

    def load(self, path: Path) -> dict[str, TrialBalance]:
        """합계잔액시산표 엑셀을 읽어 계정코드→TrialBalance 딕셔너리를 반환한다.

        멀티헤더 양식(R1·R2 두 행 헤더)을 자동 감지하며,
        단일 헤더 양식과 멀티헤더 양식 모두 지원한다.

        Args:
            path: 합계잔액시산표 엑셀 파일 경로

        Returns:
            계정코드 → TrialBalance 딕셔너리

        Raises:
            FileNotFoundError: 파일이 없을 때
        """
        if not path.exists():
            raise FileNotFoundError(f"TB 파일을 찾을 수 없습니다: {path}")

        logger.info("TB 마스터 적재 시작: %s", path)
        xl = pd.ExcelFile(path, engine="openpyxl")

        # 양식 감지 순서:
        #   1. 단일헤더 분할시트 양식 (R0=헤더, 기초잔액/차변누계/대변누계 컬럼 보유)
        #   2. 멀티헤더 양식 (R0·R1 두 행 헤더)
        #   3. 기타 단일헤더 양식 (레거시 경로)

        # 단일헤더 분할시트 양식 감지: 첫 번째 시트의 R0로 판별
        first_sheet = xl.sheet_names[0] if xl.sheet_names else None
        if first_sheet:
            df_probe = pd.read_excel(xl, sheet_name=first_sheet, header=None, nrows=1, dtype=str)
            r0 = [self._safe_str(v) for v in df_probe.iloc[0]] if df_probe.shape[0] > 0 else []
            if self._detect_split_header_format(r0):
                logger.info("TB 단일헤더 분할시트 양식 적재 시작")
                return self._load_split_header_tb(xl)

        # 멀티헤더 양식 감지
        if self._is_multiheader_format(xl):
            return self._load_multiheader_tb(xl)

        # 기존 단일 헤더 양식 (레거시 — 주로 기초/기말 시트 없는 단일 시트 형태)
        begin_sheet, end_sheet = self._detect_tb_sheets(xl.sheet_names)
        logger.info("TB 시트 감지 (레거시): 기초=%s, 기말=%s", begin_sheet, end_sheet)

        # 기말 시산표가 핵심 (기초는 opening_balance 용)
        closing = self._load_tb_sheet(xl, end_sheet, is_closing=True)
        opening_map = self._load_tb_sheet(xl, begin_sheet, is_closing=False)

        # 기초잔액 보강
        result: dict[str, TrialBalance] = {}
        for code, tb in closing.items():
            open_rec = opening_map.get(code)
            opening_bal = open_rec.closing_balance if open_rec else 0.0
            result[code] = TrialBalance(
                account_code=tb.account_code,
                account_name=tb.account_name,
                opening_balance=opening_bal,
                period_debit=tb.period_debit,
                period_credit=tb.period_credit,
                closing_balance=tb.closing_balance,
            )

        # 기초에는 있지만 기말에 없는 계정도 포함 (잔액 0으로 기말 처리)
        for code, open_rec in opening_map.items():
            if code not in result:
                result[code] = TrialBalance(
                    account_code=open_rec.account_code,
                    account_name=open_rec.account_name,
                    opening_balance=open_rec.closing_balance,
                    period_debit=0.0,
                    period_credit=0.0,
                    closing_balance=0.0,
                )

        logger.info("TB 마스터 적재 완료: %d계정", len(result))
        return result

    def _load_split_header_tb(self, xl: pd.ExcelFile) -> dict[str, TrialBalance]:
        """단일헤더 분할시트 합계잔액시산표를 적재한다.

        R0 헤더 키워드를 동적으로 매핑하여 회사별 컬럼명 변형을 자동으로 처리한다.

        구조:
            시트 1~2개 - 기초/기말 분리 또는 단일 시트.
            R0=헤더, R1~=데이터.
            col[0]: 과목 (계정코드+명칭 혼합 문자열)
            나머지 컬럼: _HEADER_KEYWORDS 키워드로 동적 감지:
                "기조찬액"·"기초잔액" 등 → opening
                "차변누계"·"차변계" 등 → period_debit
                "대변누계"·"대변계" 등 → period_credit (음수 → abs 처리)
                "기말잔액"·"기말" 등 → closing_single (단일 기말잔액 컬럼)
                "잔액" → closing_split (분할; BTI 양식은 차변잔액 + 대변잔액 합산)

        부호 결정: 계정코드 첫자리 테이블 (_SIGN_BY_PREFIX)
            '1', '9' → +1 (자산·명세)
            '2'~'8' → -1 (부채·자본·손익)

        기말잔액 결정 우선순위:
            1. closing_single 컬럼이 있으면 해당 값 * sign
            2. closing_split 컬럼이 있으면 분할값 합산 * sign
               (BTI 양식: col[2]=차변잔액 + col[7]=대변잔액, 각각 signed)
            3. 자기 정합: opening + period_debit - period_credit
        """
        begin_sheet, end_sheet = self._detect_tb_sheets(xl.sheet_names)
        logger.info("TB 단일헤더 분할시트 시트 감지: 기초=%s, 기말=%s", begin_sheet, end_sheet)

        if end_sheet is None:
            logger.warning("기말 시트를 찾을 수 없습니다 — 마지막 시트 사용")
            end_sheet = xl.sheet_names[-1] if xl.sheet_names else None

        if end_sheet is None:
            return {}

        df = pd.read_excel(xl, sheet_name=end_sheet, header=None, dtype=object)
        result: dict[str, TrialBalance] = {}

        if df.shape[0] < 2:
            return result

        # R0 헤더로 컬럼 인덱스 동적 감지
        r0 = [self._safe_str(v) for v in df.iloc[0]]
        col_map = self._map_split_header_columns(r0)
        logger.debug("TB 단일헤더 컬럼 매핑: %s", col_map)

        # R1~ 데이터
        for _, row in df.iloc[1:].iterrows():
            if len(row) < 2:
                continue

            raw_acct = self._safe_str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
            if not raw_acct:
                continue

            match = _ACCT_CODE_RE.match(raw_acct)
            if not match:
                continue

            account_code = match.group(1).strip()
            account_name = match.group(2).strip()

            # 컬럼 매핑 기반 값 추출
            opening_idx = col_map.get("opening")
            dr_idx = col_map.get("period_debit")
            cr_idx = col_map.get("period_credit")
            opening_raw = self._to_float(
                row.iloc[opening_idx] if opening_idx is not None else None
            )
            period_dr_raw = self._to_float(
                row.iloc[dr_idx] if dr_idx is not None else None
            )
            period_cr_raw = self._to_float(
                row.iloc[cr_idx] if cr_idx is not None else None
            )

            # 부호 결정: 계정코드 첫자리 기준
            sign = self._resolve_sign(account_code)

            opening_balance = opening_raw * sign
            period_debit = abs(period_dr_raw)
            period_credit = abs(period_cr_raw)

            # 기말잔액 결정 (우선순위):
            #   1. closing_single: 명시적 기말잔액 컬럼 (부호 반영)
            #   2. closing_split: 분할 잔액 컬럼 합산 × sign
            #      (BTI 양식: 차변잔액 컬럼 + 대변잔액 컬럼, 대변은 음수로 저장됨)
            #   3. 자기 정합: opening + period_debit - period_credit
            closing_single_idx = col_map.get("closing_single")
            closing_split_idxs = col_map.get("closing_split")

            if closing_single_idx is not None:
                closing_balance = self._to_float(row.iloc[closing_single_idx]) * sign
            elif closing_split_idxs:
                # 분할 잔액 컬럼 모두 합산 (BTI: col2=차변잔액 + col7=대변잔액)
                # 각 값은 이미 signed (대변 컬럼은 음수로 저장됨)
                split_sum = sum(
                    self._to_float(row.iloc[idx])
                    for idx in closing_split_idxs
                    if isinstance(idx, int) and idx < len(row)
                )
                closing_balance = split_sum * sign
            else:
                closing_balance = opening_balance + period_debit - period_credit

            if closing_balance >= 0:
                closing_dr, closing_cr = closing_balance, 0.0
            else:
                closing_dr, closing_cr = 0.0, abs(closing_balance)

            result[account_code] = TrialBalance(
                account_code=account_code,
                account_name=account_name,
                opening_balance=opening_balance,
                period_debit=period_debit,
                period_credit=period_credit,
                closing_balance=closing_balance,
                opening_dr=opening_balance if opening_balance >= 0 else 0.0,
                opening_cr=abs(opening_balance) if opening_balance < 0 else 0.0,
                closing_dr=closing_dr,
                closing_cr=closing_cr,
            )

        logger.info("TB 단일헤더 분할시트 적재 완료: %d계정 (시트: %s)", len(result), end_sheet)
        return result

    def _map_split_header_columns(self, r0: list[str]) -> dict[str, int | list[int]]:
        """R0 헤더에서 표준 필드별 컬럼 인덱스를 매핑한다.

        _HEADER_KEYWORDS 테이블의 키워드 부분 매칭으로 동적 감지한다.

        기말잔액 처리 전략:
            1. "기말잔액", "기말", "당기말" 등 명시적 키워드가 있으면
               closing_single 필드에 해당 인덱스를 저장한다.
            2. 명시적 기말 키워드가 없고 "잔액" 컬럼이 있으면
               closing_split 필드에 인덱스 목록을 저장한다.
               (BTI 양식: col[2]=차변잔액, col[7]=대변잔액 합산)

        Returns:
            표준 필드명 → 컬럼 인덱스 또는 인덱스 목록 딕셔너리
        """
        col_map: dict[str, int | list[int]] = {}
        split_closing_candidates: list[int] = []

        for i, header in enumerate(r0):
            h = header.lower()

            # 개별 필드 선착 매핑 (첫 번째 매칭 사용)
            for field in ("opening", "period_debit", "period_credit"):
                if field not in col_map and any(
                    kw in h for kw in _HEADER_KEYWORDS[field]
                ):
                    col_map[field] = i
                    break

            # closing_single: 명시적 기말잔액 키워드 (첫 번째 매칭)
            if "closing_single" not in col_map and any(
                kw in h for kw in _HEADER_KEYWORDS["closing_single"]
            ):
                col_map["closing_single"] = i

            # closing_split: "잔액" 키워드 후보 수집 (복수 허용)
            if any(kw in h for kw in _HEADER_KEYWORDS["closing_split"]):
                # opening 컬럼 이후에 위치한 것만 기말잔액 후보로 인정
                split_closing_candidates.append(i)

        # opening 이후의 "잔액" 컬럼만 분할 기말잔액으로 사용
        opening_idx = col_map.get("opening", -1)
        valid_splits = [
            c for c in split_closing_candidates
            if isinstance(opening_idx, int) and c > opening_idx
        ]
        if valid_splits and "closing_single" not in col_map:
            col_map["closing_split"] = valid_splits

        return col_map

    def _resolve_sign(self, account_code: str) -> int:
        """계정코드에 대한 부호 인수를 반환한다.

        재무상태표(B) 계정은 자산(차변잔액)과 부채·자본(대변잔액)이 혼재하므로
        COA account_type 'B'만으로 부호를 결정할 수 없다.
        코드 첫자리가 더 직접적인 신호이므로 항상 첫자리 테이블을 기준으로 사용한다.

        COA account_type은 A03의 손익계정 판별(_is_income_statement_account)에서
        활용하며, TB 부호 결정에는 관여하지 않는다.

        부호 결정: 계정코드 첫자리 테이블 (_SIGN_BY_PREFIX):
            '1', '9' → +1 (자산·명세; 차변잔액 계정)
            '2'~'8' → -1 (부채·자본·손익; 대변잔액 계정)

        Args:
            account_code: 정규화된 계정코드 문자열

        Returns:
            +1 또는 -1
        """
        stripped = account_code.lstrip("0")
        if stripped:
            return _SIGN_BY_PREFIX.get(stripped[0], -1)
        return -1

    @staticmethod
    def _detect_split_header_format(headers_r0: list[str]) -> bool:
        """단일헤더 분할시트 합계잔액시산표 양식 감지.

        R0 헤더에 기초잔액 키워드("기조찬액", "기초잔액" 등)와
        차변/대변 누계 키워드가 모두 포함된 경우 분할시트 단일헤더로 판단한다.

        컬럼명이 회사마다 달라도 키워드 포함 여부로 감지하므로
        BTI·영림원·더존 등 다양한 양식에 대응할 수 있다.

        Args:
            headers_r0: 시트 R0(첫 번째 행)의 문자열 목록

        Returns:
            단일헤더 분할시트 양식이면 True
        """
        if not headers_r0:
            return False

        joined = " ".join(headers_r0).lower()

        # 기초잔액 관련 키워드
        has_opening = any(kw in joined for kw in _HEADER_KEYWORDS["opening"])
        # 차변 누계 관련 키워드
        has_dr = any(kw in joined for kw in _HEADER_KEYWORDS["period_debit"])
        # 대변 누계 관련 키워드
        has_cr = any(kw in joined for kw in _HEADER_KEYWORDS["period_credit"])

        return has_opening and has_dr and has_cr

    def _is_multiheader_format(self, xl: pd.ExcelFile) -> bool:
        """멀티헤더 양식(R1·R2 두 행 헤더) 여부를 감지한다.

        판단 기준 (모두 충족해야 멀티헤더):
            1. 첫 번째 시트의 R0에 "차변"/"대변" 반복 패턴이 있고
            2. R1에 "잔액", "이월", "당기" 등의 세부 항목(텍스트)이 있으며
            3. R1이 BTI 단일헤더 양식("기조찬액" 키워드 포함)이 아닐 것.

        BTI 양식은 R0에 "기조찬액"이 포함되어 있어 멀티헤더와 구별된다.
        BTI R1에는 이미 숫자 데이터가 들어오므로 멀티헤더 조건(3)에서 탈락한다.
        """
        if not xl.sheet_names:
            return False

        # 첫 번째 시트(또는 연도명 시트) 사용
        target = xl.sheet_names[0]
        df_head = pd.read_excel(xl, sheet_name=target, header=None, nrows=2, dtype=str)
        if df_head.shape[0] < 2:
            return False

        r0_vals = [self._safe_str(v) for v in df_head.iloc[0]]
        r1_vals = [self._safe_str(v).lower() for v in df_head.iloc[1]]

        # 단일헤더 분할시트 양식이면 멀티헤더로 분기하지 않는다
        if self._detect_split_header_format(r0_vals):
            logger.info("TB 단일헤더 양식 감지 — 멀티헤더 경로 생략: %s", target)
            return False

        r0_lower = [v.lower() for v in r0_vals]
        has_dr_cr_r0 = sum(1 for v in r0_lower if "차변" in v or "대변" in v) >= 4
        has_detail_r1 = any(
            "잔액" in v or "이월" in v or "당기" in v or "월계" in v
            for v in r1_vals
        )

        if has_dr_cr_r0 and has_detail_r1:
            logger.info("TB 멀티헤더 양식 감지: %s", target)
            return True
        return False

    def _load_multiheader_tb(self, xl: pd.ExcelFile) -> dict[str, TrialBalance]:
        """멀티헤더 합계잔액시산표를 적재한다.

        R1·R2를 결합하여 컬럼명을 구성한다:
            - R1="차변" + R2="잔액" → "차변_잔액" (기말 차변)
            - R1="차변" + R2="이월" → "차변_이월" (기초 차변)
            - R1="차변" + R2="당기" → "차변_당기" (당기 차변 발생)
            - R1="대변" + R2="이월" → "대변_이월" (기초 대변)
            - R1="대변" + R2="당기" → "대변_당기" (당기 대변 발생)
            - R1="대변" + R2="잔액" → "대변_잔액" (기말 대변)

        연도별 시트가 있으면 최신 연도(시트 이름 최대값) 시트를 사용한다.
        """
        # 최신 연도 시트 탐색 (숫자가 가장 큰 시트명)
        result: dict[str, TrialBalance] = {}
        year_sheets = sorted(xl.sheet_names, reverse=True)
        target = year_sheets[0]

        logger.info("TB 멀티헤더 적재 시트: %s", target)

        df_raw = pd.read_excel(xl, sheet_name=target, header=None, dtype=object)
        if df_raw.shape[0] < 3:
            return result

        # R1·R2 결합 컬럼명 생성
        r1 = [self._safe_str(v) for v in df_raw.iloc[0]]
        r2 = [self._safe_str(v) for v in df_raw.iloc[1]]
        combined_cols: list[str] = []
        prev_r1 = ""
        for a, b in zip(r1, r2):
            top = a if a else prev_r1  # R1이 빈 경우 병합 셀 처리 (이전 값 유지)
            if a:
                prev_r1 = a
            if top and b:
                combined_cols.append(f"{top}_{b}")
            elif b:
                combined_cols.append(b)
            elif top:
                combined_cols.append(top)
            else:
                combined_cols.append("")

        logger.debug("TB 멀티헤더 결합 컬럼: %s", combined_cols)

        # 표준 필드 매핑
        col_idx: dict[str, int] = {}
        for i, col in enumerate(combined_cols):
            col_norm = col.lower()
            if "계정코드" in col_norm and "계정코드" not in col_idx:
                col_idx["account_code"] = i
            elif "계정명" in col_norm and "account_name" not in col_idx:
                col_idx["account_name"] = i
            elif "차변_이월" in col_norm:
                col_idx["opening_dr"] = i
            elif "대변_이월" in col_norm:
                col_idx["opening_cr"] = i
            elif "차변_당기" in col_norm:
                col_idx["period_dr"] = i
            elif "대변_당기" in col_norm:
                col_idx["period_cr"] = i
            elif "차변_잔액" in col_norm:
                col_idx["closing_dr"] = i
            elif "대변_잔액" in col_norm:
                col_idx["closing_cr"] = i

        logger.debug("TB 멀티헤더 컬럼 인덱스: %s", col_idx)

        # R3~ 데이터 행 처리
        for _, row in df_raw.iloc[2:].iterrows():
            # 계정코드 추출
            code_raw = ""
            if "account_code" in col_idx:
                code_raw = self._safe_str(row.iloc[col_idx["account_code"]])
            if not code_raw or not re.search(r"\d", code_raw):
                continue

            # 숫자만 추출하여 계정코드로 사용
            code_clean = re.sub(r"[^\d]", "", code_raw).strip()
            if not code_clean:
                continue

            name = ""
            if "account_name" in col_idx:
                name = self._safe_str(row.iloc[col_idx["account_name"]])

            opening_dr = self._to_float(row.iloc[col_idx["opening_dr"]] if "opening_dr" in col_idx else None)
            opening_cr = self._to_float(row.iloc[col_idx["opening_cr"]] if "opening_cr" in col_idx else None)
            period_dr = self._to_float(row.iloc[col_idx["period_dr"]] if "period_dr" in col_idx else None)
            period_cr = self._to_float(row.iloc[col_idx["period_cr"]] if "period_cr" in col_idx else None)
            closing_dr = self._to_float(row.iloc[col_idx["closing_dr"]] if "closing_dr" in col_idx else None)
            closing_cr = self._to_float(row.iloc[col_idx["closing_cr"]] if "closing_cr" in col_idx else None)

            # 기초잔액: 차변 이월 - 대변 이월 (순잔액)
            opening_balance = opening_dr - opening_cr
            # 기말잔액: 차변 잔액 - 대변 잔액 (순잔액)
            closing_balance = closing_dr - closing_cr

            result[code_clean] = TrialBalance(
                account_code=code_clean,
                account_name=name,
                opening_balance=opening_balance,
                period_debit=period_dr,
                period_credit=period_cr,
                closing_balance=closing_balance,
                opening_dr=opening_dr,
                opening_cr=opening_cr,
                closing_dr=closing_dr,
                closing_cr=closing_cr,
            )

        logger.info("TB 멀티헤더 적재 완료: %d계정 (시트: %s)", len(result), target)
        return result

    @staticmethod
    def _detect_tb_sheets(sheet_names: list[str]) -> tuple[str | None, str | None]:
        """TB 파일에서 기초/기말 시트를 자동 감지한다.

        우선순위:
            1. "기초" 또는 월이 01~03인 날짜 패턴 → 기초
            2. "기말" 또는 월이 10~12인 날짜 패턴 → 기말
            3. 시트가 2개면 첫 번째=기초, 두 번째=기말
            4. 시트가 1개면 기말로 처리
        """
        _date_re = re.compile(r"(\d{4})[./\-](\d{1,2})")

        begin: str | None = None
        end: str | None = None

        for sn in sheet_names:
            sn_lower = sn.lower()
            m = _date_re.search(sn)
            if m:
                month = int(m.group(2))
                if month <= 3 and begin is None:
                    begin = sn
                elif month >= 10 and end is None:
                    end = sn
            elif "기초" in sn_lower and begin is None:
                begin = sn
            elif "기말" in sn_lower and end is None:
                end = sn

        # 날짜/키워드 감지 실패 fallback
        if begin is None and end is None:
            if len(sheet_names) == 1:
                end = sheet_names[0]
            elif len(sheet_names) >= 2:
                begin = sheet_names[0]
                end = sheet_names[-1]

        return begin, end

    def _load_tb_sheet(
        self,
        xl: pd.ExcelFile,
        sheet_name: str | None,
        is_closing: bool,
    ) -> dict[str, TrialBalance]:
        """단일 시산표 시트를 읽는다.

        컬럼 구조 (header 없음):
            [0] 계정과목 (코드+명칭 혼합, 예: '      11101010  현금')
            [1] 기초잔액 (opening)
            [2] 숫자 (사용 안 함)
            [3] 기말잔액 (closing)
            [4] 당기차변 누계
            [5] 당기대변 누계 (음수)
        """
        available = xl.sheet_names
        target = sheet_name

        if target is None or target not in available:
            logger.warning("TB 시트 없음: %s (사용 가능: %s)", sheet_name, available)
            return {}

        df = pd.read_excel(xl, sheet_name=target, header=None, dtype=object)
        result: dict[str, TrialBalance] = {}

        for _, row in df.iterrows():
            if len(row) < 4:
                continue

            # 계정과목은 컬럼 0 (코드+명칭 혼합 문자열)
            raw_acct = self._safe_str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
            if not raw_acct:
                continue

            match = _ACCT_CODE_RE.match(raw_acct)
            if not match:
                continue

            account_code = match.group(1).strip()
            account_name = match.group(2).strip()

            # [1]=기초, [3]=기말, [4]=당기차변, [5]=당기대변(음수 → abs)
            period_debit = abs(self._to_float(row.iloc[4] if len(row) > 4 else None))
            period_credit = abs(self._to_float(row.iloc[5] if len(row) > 5 else None))
            closing_balance = self._to_float(row.iloc[3] if len(row) > 3 else None)

            result[account_code] = TrialBalance(
                account_code=account_code,
                account_name=account_name,
                opening_balance=0.0,
                period_debit=period_debit,
                period_credit=period_credit,
                closing_balance=closing_balance,
            )

        logger.debug("TB 시트 '%s' 적재: %d계정", target, len(result))
        return result

    @staticmethod
    def _safe_str(val: object) -> str:
        """None/NaN을 빈 문자열로 변환한다."""
        if val is None:
            return ""
        s = str(val).strip()
        return "" if s.lower() in ("nan", "none", "nat") else s

    @staticmethod
    def _to_float(val: object) -> float:
        """숫자로 변환한다. 실패 시 0.0 반환."""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).replace(",", "").strip()
        if not s or s.lower() in ("nan", "none"):
            return 0.0
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0
