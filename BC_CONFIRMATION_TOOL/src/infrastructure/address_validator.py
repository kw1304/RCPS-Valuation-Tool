import httpx
import os

JUSO_ENDPOINT = "https://www.juso.go.kr/addrlink/addrLinkApi.do"

class AddressValidator:
    """juso.go.kr OpenAPI 기반 도로명주소 검증."""

    def __init__(self, confm_key: str | None = None):
        self.confm_key = confm_key or os.getenv("JUSO_CONFM_KEY", "")

    def validate(self, address: str) -> dict:
        if not address or not self.confm_key:
            return {"status": "failed", "reason": "missing key or address"}
        params = {
            "confmKey": self.confm_key,
            "currentPage": 1, "countPerPage": 1,
            "keyword": address, "resultType": "json",
        }
        try:
            r = httpx.get(JUSO_ENDPOINT, params=params, timeout=8.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return {"status": "failed", "reason": str(e)}
        results = data.get("results", {})
        total = int(results.get("common", {}).get("totalCount", "0") or 0)
        if total == 0:
            return {"status": "not_found", "input": address}
        top = results["juso"][0]
        zipcode = top.get("zipNo", "")
        suggested = top.get("roadAddr", "")
        if address.strip() == suggested.strip():
            return {"status": "ok", "zipcode": zipcode, "address": suggested}
        return {"status": "mismatch", "zipcode": zipcode, "suggested": suggested, "input": address}
