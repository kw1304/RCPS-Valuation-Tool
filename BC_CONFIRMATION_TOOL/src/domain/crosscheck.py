from rapidfuzz import fuzz

Party = tuple[str, str | None]  # (canonical, branch)


def _key(p: Party) -> str:
    """Generate string key for party tuple (canonical, branch)."""
    c, b = p
    return f"{c}|{b or ''}"


def bidirectional_compare(extracted: list[Party], cs: list[Party]) -> list[dict]:
    """4-1. 회사 CS ↔ 우리 추출 양방향 비교.

    Returns list of dicts with:
    - canonical: 계좌명
    - branch: 지점
    - status: "both" | "missing_in_cs" | "extra_in_cs"
    """
    ex_keys = {_key(p) for p in extracted}
    cs_keys = {_key(p) for p in cs}
    result = []

    # extracted에 있는 항목: both 또는 missing_in_cs
    for p in extracted:
        k = _key(p)
        status = "both" if k in cs_keys else "missing_in_cs"
        result.append({"canonical": p[0], "branch": p[1], "status": status})

    # cs에만 있는 항목: extra_in_cs
    for p in cs:
        k = _key(p)
        if k not in ex_keys:
            result.append({"canonical": p[0], "branch": p[1], "status": "extra_in_cs"})

    return result


def prior_compare(current: list[Party], prior: list[Party], threshold: float = 0.85) -> list[dict]:
    """4-2. 전기 CS ↔ 당기 (canonical + fuzzy).

    Returns list of dicts with:
    - canonical: 당기 계좌명
    - branch: 당기 지점
    - status: "both" | "current_only" | "prior_only"
    - matched_prior: (matched_canonical, matched_branch) or None
    """
    result = []

    # current의 각 항목: prior와 매칭 시도 (exact key 또는 fuzzy)
    for cur in current:
        ck = _key(cur)
        match = None

        # exact match 먼저 시도
        for pri in prior:
            pk = _key(pri)
            if ck == pk:
                match = pri
                break

        # exact match 없으면 fuzzy match 시도 (partial_ratio for substring matching)
        if not match:
            for pri in prior:
                ratio = fuzz.partial_ratio(cur[0], pri[0]) / 100.0
                if ratio >= threshold and (cur[1] or "") == (pri[1] or ""):
                    match = pri
                    break

        status = "both" if match else "current_only"
        result.append({
            "canonical": cur[0],
            "branch": cur[1],
            "status": status,
            "matched_prior": match
        })

    # prior에만 있는 항목: prior_only
    for pri in prior:
        matched = False
        for cur in current:
            pk = _key(pri)
            ck = _key(cur)
            # exact match 또는 fuzzy match 확인
            if pk == ck:
                matched = True
                break
            ratio = fuzz.partial_ratio(pri[0], cur[0]) / 100.0
            if ratio >= threshold and (pri[1] or "") == (cur[1] or ""):
                matched = True
                break

        if not matched:
            result.append({
                "canonical": pri[0],
                "branch": pri[1],
                "status": "prior_only",
                "matched_prior": None
            })

    return result


def listed_in_cs(targets: list[Party], cs: list[Party]) -> list[dict]:
    """4-3·4-4. targets(월보 or 담보·보증 명세서) 각 항목이 CS에 존재하는지 Y/N.

    Returns list of dicts with:
    - canonical: 계좌명
    - branch: 지점
    - present: True | False
    """
    cs_keys = {_key(p) for p in cs}
    out = []
    for t in targets:
        present = _key(t) in cs_keys
        out.append({
            "canonical": t[0],
            "branch": t[1],
            "present": present
        })
    return out
