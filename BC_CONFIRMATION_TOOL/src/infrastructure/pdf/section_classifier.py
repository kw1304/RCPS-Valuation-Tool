import re

SECTION_RULES = [
    # 우선순위: specific 보증·담보·파생을 먼저 (연대보증·담보제공 라인이 AC1에 흘러가지 않도록)
    ("AC4", ["지급보증", "연대보증", "보증채무", "L/C", "신용장"]),
    ("AC5", ["담보제공", "근저당", "질권", "담보견질"]),
    ("AC3", ["파생", "선도", "스왑", "옵션", "FX"]),
    ("AC2", ["차입", "대출", "한도", "약정", "사채"]),
    ("AC7", ["보험증권", "보험상품", "보험계약", "가입"]),
    ("AC6", ["어음", "수표", "당좌개설"]),
    # AC1 (금융자산) — 가장 광범위, 마지막
    ("AC1", ["예금", "계좌", "잔액", "주식", "채권", "펀드", "수익증권", "CMA", "MMF", "RP", "CP", "CD", "신탁", "ETF", "외화예금", "발행어음", "랩", "위탁자", "종합투자"]),
]


def classify_sections(text: str) -> dict[str, str]:
    """텍스트 → 섹션별 substring (line-level greedy).

    Args:
        text: 은행 거래 확인서 텍스트

    Returns:
        AC1~AC8 섹션별 텍스트 매핑. 키워드 매칭에 따라 줄을 분류하고,
        한 번 섹션에 할당되면 이후 줄은 같은 섹션에 계속 누적.
    """
    lines = text.splitlines()
    out: dict[str, list[str]] = {f"AC{i}": [] for i in range(1, 9)}
    current = None

    for line in lines:
        s = line.strip()
        if not s:
            continue

        matched = None
        for ac, kws in SECTION_RULES:
            if any(kw in s for kw in kws):
                matched = ac
                break

        if matched:
            current = matched

        if current:
            out[current].append(s)
        else:
            out["AC8"].append(s)  # 미분류 → 일반거래

    return {k: "\n".join(v) for k, v in out.items() if v}
