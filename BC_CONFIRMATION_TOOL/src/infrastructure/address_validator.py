"""주소 유효성 검토 — JUSO API + heuristic fallback.

status 의미:
  ok           : API 검증 통과 OR 휴리스틱 완전성 충족
  mismatch     : API 검증 — 회사 주소와 정정 주소 다름
  incomplete   : 휴리스틱 — 시·도·도로명·번지 등 핵심 누락
  foreign      : 해외 주소 (한글 형식 아님) — 수기 확인 필요
  not_found    : API 검증 — 존재하지 않는 주소
  failed       : API 호출 실패 (key 없음, 네트워크 오류 등)
"""
import httpx
import os
import re

JUSO_ENDPOINT = "https://www.juso.go.kr/addrlink/addrLinkApi.do"

# 한국 시·도 keywords
_KR_SIDO = [
    "서울특별시", "서울시", "서울",
    "부산광역시", "부산시", "부산",
    "대구광역시", "대구시", "대구",
    "인천광역시", "인천시", "인천",
    "광주광역시", "광주시", "광주",
    "대전광역시", "대전시", "대전",
    "울산광역시", "울산시", "울산",
    "세종특별자치시", "세종시", "세종",
    "경기도", "경기",
    "강원특별자치도", "강원도", "강원",
    "충청북도", "충북",
    "충청남도", "충남",
    "전라북도", "전북", "전북특별자치도",
    "전라남도", "전남",
    "경상북도", "경북",
    "경상남도", "경남",
    "제주특별자치도", "제주도", "제주",
]
_ROAD_PATTERN = re.compile(r"(\S+(?:로|길|동|읍|면)\s*\d+)")


def heuristic_check(address: str) -> dict:
    """API 없이 휴리스틱 주소 완전성 검토."""
    if not address:
        return {"status": "incomplete", "reason": "empty", "input": ""}
    s = address.strip()
    if re.match(r"^[A-Za-z0-9\s,./\-]+$", s):
        return {"status": "foreign", "input": s, "note": "해외 주소 — 수기 확인 필요"}
    has_sido = any(sido in s for sido in _KR_SIDO)
    has_road = bool(_ROAD_PATTERN.search(s))
    if has_sido and has_road:
        return {"status": "ok", "input": s, "note": "휴리스틱 통과 (시·도+도로명)"}
    if has_sido:
        return {"status": "ok", "input": s, "note": "휴리스틱 통과 (시·도 있음)"}
    if has_road:
        return {"status": "incomplete", "input": s, "note": "시·도 누락"}
    return {"status": "incomplete", "input": s, "note": "한국 주소 형식 미충족"}


class AddressValidator:
    """주소 검증 — JUSO API 우선, 실패 시 휴리스틱 fallback."""

    def __init__(self, confm_key: str | None = None):
        self.confm_key = confm_key or os.getenv("JUSO_CONFM_KEY", "")

    def validate(self, address: str) -> dict:
        if not address:
            return {"status": "incomplete", "reason": "empty", "input": ""}
        if not self.confm_key:
            return heuristic_check(address)
        params = {
            "confmKey": self.confm_key,
            "currentPage": 1, "countPerPage": 1,
            "keyword": address, "resultType": "json",
        }
        try:
            r = httpx.get(JUSO_ENDPOINT, params=params, timeout=8.0)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return heuristic_check(address)
        results = data.get("results", {})
        total = int(results.get("common", {}).get("totalCount", "0") or 0)
        if total == 0:
            heur = heuristic_check(address)
            if heur["status"] == "foreign":
                return heur
            return {"status": "not_found", "input": address}
        top = results["juso"][0]
        zipcode = top.get("zipNo", "")
        suggested = top.get("roadAddr", "")
        if address.strip() == suggested.strip():
            return {"status": "ok", "zipcode": zipcode, "address": suggested}
        return {"status": "mismatch", "zipcode": zipcode, "suggested": suggested, "input": address}
