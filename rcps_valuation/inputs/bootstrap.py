"""이자율 부트스트래핑 — Par yield bond bootstrap.

이전엔 핵심 수학이 프론트엔드 JS(frontend/index.html)에 있어 자동 회귀 테스트·재현성 부재.
본 모듈로 이관하여 K-IFRS 13 BC176 "관측가능 input의 충실한 표현"을 위한 결정론적 재현 보장.

표준:
  par yield bond bootstrap (한국 국고채·KIS-Net 민평 회사채 컨벤션)
  - 시장 YTM을 par yield(액면 거래 채권의 쿠폰)로 가정
  - 한국 국고채는 액면 근처 거래되어 YTM ≈ par yield 근사가 합리적
  - BBB 이하 신용에선 편향 가능 → 평가조서 컨벤션 명시 권장
"""
from typing import Dict, List, Optional, Sequence, Tuple
import math


def _interp_ytm(t: float, rows: Sequence[dict]) -> float:
    """선형 보간 + 평탄 외삽 (만기 t년의 YTM %)."""
    sorted_rows = sorted([r for r in rows if r.get("t") and r.get("y")],
                         key=lambda r: r["t"])
    if not sorted_rows:
        return 0.0
    if t <= sorted_rows[0]["t"]:
        return sorted_rows[0]["y"]
    if t >= sorted_rows[-1]["t"]:
        return sorted_rows[-1]["y"]
    for i in range(len(sorted_rows) - 1):
        a, b = sorted_rows[i], sorted_rows[i + 1]
        if a["t"] <= t <= b["t"]:
            w = (t - a["t"]) / (b["t"] - a["t"])
            return a["y"] + w * (b["y"] - a["y"])
    return sorted_rows[-1]["y"]


def _interp_df(t: float, dfs: Dict[float, float]) -> float:
    """log-linear DF 보간 (zero-rate 선형보간과 동치)."""
    keys = sorted(dfs.keys())
    if not keys:
        return 1.0
    if t in dfs:
        return dfs[t]
    if t <= keys[0]:
        # 평탄 외삽: z(t<t_min) = z(t_min)
        z = -math.log(dfs[keys[0]]) / keys[0] if keys[0] > 0 else 0.0
        return math.exp(-z * t)
    if t >= keys[-1]:
        z = -math.log(dfs[keys[-1]]) / keys[-1] if keys[-1] > 0 else 0.0
        return math.exp(-z * t)
    for i in range(len(keys) - 1):
        a, b = keys[i], keys[i + 1]
        if a <= t <= b:
            za = -math.log(dfs[a]) / a
            zb = -math.log(dfs[b]) / b
            w = (t - a) / (b - a)
            z = za + w * (zb - za)
            return math.exp(-z * t)
    return math.exp(-keys[-1] * t)


def bootstrap_par_yield(rows: Sequence[dict], m: int = 2,
                         max_T: float = 20.0) -> dict:
    """par yield bootstrap.

    rows: [{"t": 만기(년), "y": YTM(%)}, ...]
    m: 쿠폰 주기 (Rf=2 반기, Rd=4 분기)
    max_T: 부트스트랩 최대 만기 (한국 RCPS 표준 3~5년이라 20년 cap)

    Returns:
        {
          "mid_rows": [{"T", "step", "ytm_per", "zper", "df"}, ...] (m간격),
          "out_rows": [{"T", "df", "zper", "zcont"}, ...] (0.25년 간격 보간 결과),
          "dfs": {T: df, ...},
          "input_max": 입력 데이터 최대 만기,
          "max_T_used": 실제 부트스트랩 최대 만기,
          "warning": "20년 초과 입력 silent drop" 등 경고 문자열 or None,
        }
    """
    dt = 1.0 / m
    valid = sorted([dict(r) for r in rows if r.get("t", 0) > 0 and r.get("y", 0) > 0],
                   key=lambda r: r["t"])
    if not valid:
        return {"mid_rows": [], "out_rows": [], "dfs": {}, "warning": None,
                "input_max": 0, "max_T_used": 0}

    input_max = valid[-1]["t"]
    max_T_used = min(input_max, max_T)
    warning = None
    if input_max > max_T:
        warning = f"만기 {max_T}년 초과 입력({input_max}년) — 부트스트랩에서 제외됨"

    dfs: Dict[float, float] = {}
    mid_rows = []

    T = dt
    step = 1
    while T <= max_T_used + 1e-9:
        Tr = round(T * 1000) / 1000
        ytm = _interp_ytm(Tr, valid)
        c = ytm / 100.0 / m
        sum_pv = 0.0
        ti = dt
        while ti < Tr - 1e-9:
            tir = round(ti * 1000) / 1000
            sum_pv += c * _interp_df(tir, dfs)
            ti = round((ti + dt) * 1000) / 1000
        df = (1.0 - sum_pv) / (1.0 + c)
        if df > 0 and df < 2 and not math.isnan(df):
            dfs[Tr] = df
            zper = math.pow(df, -1.0 / step) - 1
            mid_rows.append({"T": Tr, "step": step, "ytm_per": ytm / m,
                             "zper": zper * 100, "df": df})
        T = round((T + dt) * 1000) / 1000
        step += 1

    # 출력 grid: 0.25년 간격
    out_rows = []
    oT = 0.25
    while oT <= max_T_used + 1e-9:
        oTr = round(oT * 1000) / 1000
        df = _interp_df(oTr, dfs)
        if df > 0 and not math.isnan(df):
            n = oTr * m
            zper = math.pow(df, -1.0 / n) - 1 if n > 0 else 0.0
            zcont = m * math.log(1 + zper) if zper > -1 else 0.0
            out_rows.append({"T": oTr, "df": df, "zper": zper * 100,
                             "zcont": zcont * 100})
        oT = round((oT + 0.25) * 1000) / 1000

    return {
        "mid_rows": mid_rows,
        "out_rows": out_rows,
        "dfs": dfs,
        "input_max": input_max,
        "max_T_used": max_T_used,
        "warning": warning,
    }


def spot_curve_from_bootstrap(result: dict) -> List[Tuple[float, float]]:
    """부트스트랩 결과에서 연속 스팟 곡선 (T, z_continuous_decimal) 추출.
    api/app.py의 rf_spot/rd_spot 형식."""
    return [(r["T"], r["zcont"] / 100.0) for r in result.get("out_rows", [])]
