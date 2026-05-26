"""금리 곡선 변환 헬퍼 — 4모형(TF·GS·MC·BDT)·후속측정·민감도 공유 단일 출처.

이전엔 api/app.py와 valuation/subsequent.py에 동일 목적 함수가 별도로 존재해서
한 곳만 수정 시 silent divergence 위험 → 본 모듈로 통합.
"""
from typing import List, Optional, Sequence


def spot_to_step_forwards(spot_pts: Sequence[Sequence[float]],
                           T: float, steps: int) -> Optional[List[float]]:
    """선형보간(linear-on-spot) + 평탄 외삽 → 스텝별 연속 forward rate.

    spot_pts : list of [t_years, z_continuous_decimal]  (z = 연속 스팟)
    T        : 총 기간(년),  steps : 등간격 스텝 수

    - 연속 스팟 z(t)를 만기 사이 선형보간, 최단물 미만/최장물 초과는 평탄 외삽
    - 스텝 i (t1=i·dt, t2=(i+1)·dt): f_i = (z(t2)·t2 − z(t1)·t1)/(t2−t1)
    - i=0(t1=0) 구간은 0/0 회피로 zget(t2) 사용 (의미상: 0~t2 forward = z(t2))
    Returns list of length `steps`, or None on invalid input. Never raises.

    Σ f_k · dt = z(T) · T 의 telescoping 관계가 항상 성립 (K-IFRS 1109 만기 매칭).
    """
    try:
        if not spot_pts or steps <= 0 or T <= 0:
            return None
        raw = []
        for pt in spot_pts:
            try:
                t_yr, z_c = float(pt[0]), float(pt[1])
                if t_yr is not None and z_c is not None and t_yr > 0:
                    raw.append((t_yr, z_c))
            except (TypeError, ValueError, IndexError):
                continue
        if not raw:
            return None
        raw.sort(key=lambda x: x[0])
        t_last, z_last = raw[-1]

        def zget(t):
            if t <= raw[0][0]:
                return raw[0][1]
            if t >= t_last:
                return z_last
            for k in range(len(raw) - 1):
                t0, z0 = raw[k]
                t1, z1 = raw[k + 1]
                if t0 <= t <= t1:
                    w = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                    return z0 + w * (z1 - z0)
            return z_last

        dt = T / steps
        out = []
        for i in range(steps):
            t1 = i * dt
            t2 = (i + 1) * dt
            za = zget(t1)
            zb = zget(t2)
            if t2 - t1 <= 0:
                out.append(zb)
            elif t1 == 0:
                # 0~t2 forward = z(t2) (zget(0)·0 항 = 0)
                out.append(zb)
            else:
                out.append((zb * t2 - za * t1) / (t2 - t1))
        return out
    except Exception:
        return None
