"""DART OPEN API client — corp_code 조회 · 공시 list · 단일회사 전체 재무제표.

opendart.fss.or.kr API:
- corpCode.xml : 회사명 → corp_code 일괄 매핑 (24h 캐시)
- list.json    : 공시 list (정기공시 A / 외부감사 F 등)
- fnlttSinglAcntAll.json : 단일회사 전체 재무제표 (당기·전기·전전기 3개년)
- document.xml : 보고서 원문 (ZIP → XML) — 외감 비상장 감사보고서 fallback용

CC_SAMPLING_TOOL_V2/client.py + rcps_valuation/dart_financials.py 이식·정리.
RP 추출 등 CC 전용 로직, DCF 전용 계정맵은 제외.
"""
from __future__ import annotations
import io
import os
import re
import time
import zipfile
import logging
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("risk.dart")

_BASE = "https://opendart.fss.or.kr/api"
_CACHE_DIR = Path.home() / ".risk_tool" / "dart_cache"


class DartError(Exception):
    pass


def _normalize_name(name: str) -> str:
    """회사명 정규화 — 공백·법인격 표기 제거 후 소문자."""
    t = (name or "").strip()
    t = re.sub(r"\(주\)|주식회사|㈜", "", t)
    t = re.sub(r"\s+", "", t)
    return t.lower()


class DartClient:
    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = (api_key or os.environ.get("DART_API_KEY", "")).strip()
        self.timeout = timeout
        self._corp_map: Optional[dict[str, list[dict]]] = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _ensure_key(self):
        if not self.api_key:
            raise DartError("DART_API_KEY 미설정 (.env 또는 환경변수)")

    # ---------- corp_code 매핑 ----------

    def load_corp_codes(self) -> dict[str, list[dict]]:
        """corpCode.xml → {정규화회사명: [{corp_code, corp_name, stock_code}]}. 24h 캐시."""
        if self._corp_map is not None:
            return self._corp_map
        self._ensure_key()
        cache_file = _CACHE_DIR / "corp_codes.xml"
        fresh = (cache_file.exists()
                 and (time.time() - cache_file.stat().st_mtime) < 86400)
        if fresh:
            xml_bytes = cache_file.read_bytes()
        else:
            try:
                resp = requests.get(f"{_BASE}/corpCode.xml",
                                    params={"crtfc_key": self.api_key},
                                    timeout=self.timeout)
            except requests.RequestException as e:
                raise DartError(f"corpCode fetch 실패: {e}") from e
            if resp.status_code != 200:
                raise DartError(f"corpCode HTTP {resp.status_code}")
            try:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    xml_bytes = zf.read("CORPCODE.xml")
            except (zipfile.BadZipFile, KeyError) as e:
                raise DartError(f"corpCode ZIP 파싱 실패: {e}") from e
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(xml_bytes)
            except OSError:
                pass

        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml_bytes)
        out: dict[str, list[dict]] = {}
        for it in root.iter("list"):
            corp_code = (it.findtext("corp_code") or "").strip()
            corp_name = (it.findtext("corp_name") or "").strip()
            stock_code = (it.findtext("stock_code") or "").strip()
            if not corp_code or not corp_name:
                continue
            norm = _normalize_name(corp_name)
            if not norm:
                continue
            out.setdefault(norm, []).append({
                "corp_code": corp_code,
                "corp_name": corp_name,
                "stock_code": stock_code,
            })
        self._corp_map = out
        return out

    # 한글 통칭 → DART 등록 정식명(영문 등록 상장사). 한↔영 불일치 보정. 확장 가능.
    _NAME_ALIASES = {
        "네이버": "NAVER",
    }

    def find_corp_code(self, name: str) -> Optional[dict]:
        """회사명 → {corp_code, corp_name, stock_code}. 상장사(stock_code 보유) 우선."""
        if not name:
            return None
        name = self._NAME_ALIASES.get(name.strip(), name)
        cmap = self.load_corp_codes()
        target = _normalize_name(name)
        if not target:
            return None
        entries = cmap.get(target)
        if not entries:
            cand = []
            for k, items in cmap.items():
                if target in k or k in target:
                    cand.extend(items)
            entries = cand
        if not entries:
            return None
        entries = sorted(entries, key=lambda e: 0 if e["stock_code"] else 1)
        return entries[0]

    # ---------- 재무제표 ----------

    def fnlttSinglAcntAll(self, corp_code: str, bsns_year: int,
                          fs_div: str) -> Optional[list]:
        """단일 사업연도 전체 재무제표. status 000이면 list, 아니면 None.

        한 호출에 당기·전기·전전기 3개년 row 반환. reprt_code 11011 = 사업보고서.
        fs_div: CFS(연결) / OFS(별도).
        """
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": "11011",
            "fs_div": fs_div,
        }
        try:
            resp = requests.get(f"{_BASE}/fnlttSinglAcntAll.json",
                                params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise DartError(f"FS fetch 실패: {e}") from e
        if resp.status_code != 200:
            return None
        body = resp.json()
        if body.get("status") != "000":
            return None
        return body.get("list") or []

    # ---------- 공시 list ----------

    def list_disclosures(self, corp_code: str, bgn_de: str,
                         end_de: str) -> list[dict]:
        """공시 리스트. pblntf_ty 미지정(전체) — report_nm 키워드 필터는 호출측.

        Returns: [{rcept_dt, report_nm, rcept_no}]. 오류 시 빈 리스트.
        """
        params = {"crtfc_key": self.api_key, "corp_code": corp_code,
                  "bgn_de": bgn_de, "end_de": end_de, "page_count": "100"}
        try:
            resp = requests.get(f"{_BASE}/list.json", params=params,
                                timeout=self.timeout)
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        body = resp.json()
        if body.get("status") != "000":
            return []
        return [{"rcept_dt": it.get("rcept_dt"), "report_nm": it.get("report_nm"),
                 "rcept_no": it.get("rcept_no")} for it in (body.get("list") or [])]

    def company_industry(self, corp_code: str) -> Optional[str]:
        """company.json → induty_code(KSIC 표준산업분류). 오류 시 None."""
        try:
            resp = requests.get(f"{_BASE}/company.json",
                                params={"crtfc_key": self.api_key, "corp_code": corp_code},
                                timeout=self.timeout)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        body = resp.json()
        if body.get("status") != "000":
            return None
        return (body.get("induty_code") or "").strip() or None

    def is_financial(self, corp_code: str) -> bool:
        """금융·보험업(KSIC 대분류 K = 64·65·66) 여부. 조회 실패 시 False(일반기업 취급)."""
        code = self.company_industry(corp_code)
        return bool(code) and code[:2] in ("64", "65", "66")

    # ---------- 감사보고서 원문 (외감 비상장 fallback용) ----------

    def list_audit_reports(self, corp_code: str) -> list[tuple]:
        """list.json (pblntf_ty=F) → [(period_year, rcept_no, is_consolidated)]."""
        self._ensure_key()
        out = []
        try:
            resp = requests.get(f"{_BASE}/list.json", params={
                "crtfc_key": self.api_key, "corp_code": corp_code,
                "bgn_de": "20150101", "end_de": "20991231",
                "pblntf_ty": "F", "page_count": 100,
            }, timeout=self.timeout)
        except requests.RequestException as e:
            raise DartError(f"list fetch 실패: {e}") from e
        if resp.status_code != 200:
            return []
        body = resp.json()
        if body.get("status") != "000":
            return []
        for it in body.get("list") or []:
            nm = it.get("report_nm") or ""
            if "감사보고서" not in nm:
                continue
            m = re.search(r"\((\d{4})\.(\d{1,2})\)", nm)
            if not m:
                continue
            out.append((int(m.group(1)), it.get("rcept_no"), "연결" in nm))
        return out

    def fetch_document(self, rcept_no: str) -> Optional[str]:
        """보고서 원문 document.xml — ZIP 내 최대 XML → str. 캐시."""
        self._ensure_key()
        cache_file = _CACHE_DIR / f"doc_{rcept_no}.txt"
        if cache_file.exists():
            try:
                return cache_file.read_text(encoding="utf-8")
            except OSError:
                pass
        try:
            resp = requests.get(f"{_BASE}/document.xml", params={
                "crtfc_key": self.api_key, "rcept_no": rcept_no,
            }, timeout=self.timeout)
        except requests.RequestException as e:
            raise DartError(f"document fetch 실패: {e}") from e
        if resp.status_code != 200:
            return None
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xmls = [n for n in zf.namelist() if n.lower().endswith(".xml")]
                if not xmls:
                    return None
                xmls.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                text = zf.read(xmls[0]).decode("utf-8", errors="ignore")
        except (zipfile.BadZipFile, KeyError) as e:
            raise DartError(f"document ZIP 파싱 실패: {e}") from e
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return text
