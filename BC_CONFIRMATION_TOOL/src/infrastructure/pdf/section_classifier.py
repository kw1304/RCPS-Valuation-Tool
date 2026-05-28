import re

SECTION_RULES = [
    ("AC1", ["예금", "계좌", "잔액", "주식", "채권", "펀드", "수익증권", "CMA", "MMF", "RP", "CP", "CD", "신탁", "ETF", "외화예금"]),
    ("AC2", ["차입", "대출", "한도", "약정", "사채"]),
    ("AC3", ["파생", "선도", "스왑", "옵션", "FX"]),
    ("AC4", ["지급보증", "보증", "L/C", "신용장"]),
    ("AC5", ["담보", "근저당", "질권"]),
    ("AC6", ["어음", "수표", "당좌"]),
    ("AC7", ["보험증권", "보험상품", "가입"]),
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
