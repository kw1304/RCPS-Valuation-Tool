"""
Monetary Unit Sampling (MUS) — Representative sample 추출

알고리즘 (감사기준서 530 + AICPA AAG-SAM):
  표본간격 J = 잔여모집단 / 표본규모 N
  임의출발점 r0 ∈ [0, J)
  거래처를 임의 순서(또는 명세서 순서)로 정렬
  remainder = -r0
  for 각 거래처:
      remainder += 잔액
      selections = max(0, ⌊remainder / J⌋ + 1) if remainder >= 0 else 0
      hit = (selections > 0)
      remainder -= selections × J

조서 R20~R49 방식 그대로:
  R21:  remainder 초기값 = -r0 (= -530,816,314)
  각 거래처 누적금액 + 잔액 → remainder
  remainder ≥ 0 인 순간 hit (선택 횟수만큼 J 차감)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class MUSSelection:
    name: str
    balance: float
    cumulative: float
    selections: int
    remainder_after: float
    hit: bool


@dataclass
class MUSResult:
    sample_interval: float
    random_start: float
    selections: list[MUSSelection]
    sampled_names: list[str]


def run_mus(
    pool: list[tuple[str, float]],     # [(name, balance), ...] — Key item 제외된 모집단
    sample_size: int,
    sample_interval: float | None = None,
    random_start: float | None = None,
    seed: int | None = None,
) -> MUSResult:
    """MUS 추출 — 조서 알고리즘과 동일 (cumulative + remainder)"""
    if sample_size <= 0 or not pool:
        return MUSResult(sample_interval=0.0, random_start=0.0, selections=[], sampled_names=[])

    total = sum(b for _, b in pool)
    J = sample_interval if sample_interval is not None else total / sample_size
    if J <= 0:
        return MUSResult(sample_interval=0.0, random_start=0.0, selections=[], sampled_names=[])

    rng = random.Random(seed) if seed is not None else random
    r0 = random_start if random_start is not None else rng.uniform(0, J)

    selections: list[MUSSelection] = []
    cumulative = 0.0
    remainder = -r0
    sampled: list[str] = []

    for name, bal in pool:
        cumulative += bal
        remainder += bal
        sel = 0
        if remainder >= 0:
            sel = int(math.floor(remainder / J)) + 1
            remainder -= sel * J
        hit = sel > 0
        selections.append(MUSSelection(
            name=name, balance=bal, cumulative=cumulative,
            selections=sel, remainder_after=remainder, hit=hit,
        ))
        if hit:
            sampled.append(name)

    return MUSResult(
        sample_interval=J,
        random_start=r0,
        selections=selections,
        sampled_names=sampled,
    )
