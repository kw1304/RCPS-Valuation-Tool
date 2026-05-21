from dataclasses import dataclass, field
from datetime import date
from typing import Optional, List, Tuple


@dataclass
class RCPSParams:
    # ── 기본 발행 조건
    issue_date: date
    maturity_date: date
    face_value: float           # 발행금액 (원)
    coupon_rate: float          # 우선배당률 (예: 0.02 = 2%)
    coupon_frequency: str = "annual"   # "none" | "annual" | "semi" | "quarterly"

    # ── 전환 조건
    conversion_price: float = 0.0    # 전환가액 (원/주)
    conversion_start: Optional[date] = None  # 전환청구 가능 시작일

    # ── 풋옵션 (보유자 상환청구)
    put_start: Optional[date] = None     # 풋 행사 가능 시작일
    put_irr: float = 0.0                 # 보장수익률 IRR (연 복리, 예: 0.075 = 7.5%)
    # put 행사가 = face × (1+put_irr)^(issue→node 연수)
    put_price_mode: str = "irr"          # "irr"(IRR 누적 make-whole) | "fixed"(고정 행사가)
    put_fixed_price: float = 0.0         # 고정 풋 행사가액 (정액, 발행금액 스케일)

    # ── 콜옵션 (발행자 수의상환권)
    call_start: Optional[date] = None   # 콜 행사 가능 시작일
    call_irr: float = 0.0               # 수의상환 기준 IRR (연 복리, 예: 0.05 = 5%)
    call_price_mode: str = "irr"        # "irr" | "fixed"
    call_fixed_price: float = 0.0       # 고정 콜 행사가액 (정액, 발행금액 스케일)

    # ── 리픽싱 조건 (하향 조정)
    # 트리거(refixing_trigger): 주가가 현행 전환가의 이 비율 미만이면 리픽싱 발동
    #   예) refixing_trigger=0.90 → 주가 < 전환가 × 90% 일 때 전환가 하향 조정
    # 하한(refixing_floor): 최초 전환가 대비 전환가가 내려갈 수 있는 최저 한도
    #   예) refixing_floor=0.70 → 전환가는 최초 전환가의 70% 아래로 불가
    # 조정 방식: 트리거 발동 시 전환가를 시가(주가)로 하향, 단 하한 이하 불가
    #   새 전환가 = max(최초전환가 × floor, 현재주가)
    refixing: bool = False
    refixing_floor: Optional[float] = None    # 하한 비율 (예: 0.70 = 최초 전환가의 70%)
    refixing_trigger: Optional[float] = None  # 트리거 비율 (예: 0.90 = 전환가의 90%)
    refixing_frequency: str = "continuous"    # "continuous"|"quarterly"|"semi-annual"|"annual"

    # ── 시장 데이터
    stock_price: float = 0.0
    volatility: float = 0.0
    risk_free_rate: float = 0.0
    credit_spread: float = 0.0   # 신용스프레드 → Kd = rf + spread
    dividend_yield: float = 0.0

    # ── 평가기준일
    valuation_date: date = field(default_factory=date.today)

    # ── 비상장 여부
    # 비상장 기업은 stock_price를 DCF로 별도 산출 후 입력:
    #   from inputs.dcf import DCFParams, dcf_valuation
    #   dcf = dcf_valuation(DCFParams(...))
    #   params = RCPSParams(..., stock_price=dcf["stock_price"], is_unlisted=True)
    is_unlisted: bool = False

    # ── 기간구조 (선택: [(tenor_yr, rate), ...] 형태)
    yield_curve: Optional[List[Tuple[float, float]]] = None

    # ── 희석 계산용 주식수 (선택: 노드희석_구분할인)
    common_shares: Optional[float] = None   # 보통주식수
    rcps_shares: Optional[float] = None     # RCPS 주식수

    @property
    def discount_rate(self) -> float:
        return self.risk_free_rate + self.credit_spread

    @property
    def T(self) -> float:
        """평가기준일 ~ 만기 잔존연수"""
        return max((self.maturity_date - self.valuation_date).days / 365.0, 0)

    @property
    def time_to_maturity(self) -> float:
        return self.T

    @property
    def t_issue_to_val(self) -> float:
        """발행일 ~ 평가기준일 경과연수"""
        return (self.valuation_date - self.issue_date).days / 365.0

    def put_exercise_price(self, t_from_val: float) -> float:
        """
        노드 시점의 풋 행사가액 (make-whole):
        = face × (1+IRR)^t_issue - Σ coupon × (1+IRR)^(t_issue - j×interval)
        보장수익률 IRR 기준으로 누적 원리합계에서 기지급 쿠폰의 재투자가치를 차감.
        put_price_mode=="fixed" 이면 고정 행사가(정액)를 그대로 반환.
        """
        if self.put_price_mode == "fixed":
            return self.put_fixed_price if self.put_fixed_price > 0 else self.face_value
        t_from_issue = self.t_issue_to_val + t_from_val
        if self.put_irr <= 0:
            return self.face_value

        accumulated = self.face_value * ((1 + self.put_irr) ** t_from_issue)

        if self.coupon_rate <= 0 or self.coupon_frequency == "none":
            return max(self.face_value, accumulated)

        if self.coupon_frequency == "annual":
            interval = 1.0
        elif self.coupon_frequency == "semi":
            interval = 0.5
        elif self.coupon_frequency == "quarterly":
            interval = 0.25
        else:
            return max(self.face_value, accumulated)

        coupon_amount = self.face_value * self.coupon_rate * interval
        fv_coupons = 0.0
        j = 1
        while j * interval <= t_from_issue + 1e-9:
            fv_coupons += coupon_amount * ((1 + self.put_irr) ** (t_from_issue - j * interval))
            j += 1

        return max(self.face_value, accumulated - fv_coupons)

    def call_exercise_price(self, t_from_val: float) -> float:
        """
        발행자 콜 행사가액 (수의상환권):
        = face × (1+call_irr)^(발행일→노드 경과연수)
        call_price_mode=="fixed" 이면 고정 행사가(정액)를 그대로 반환.
        call_irr <= 0 이면 face 그대로 반환
        """
        if self.call_price_mode == "fixed":
            return self.call_fixed_price if self.call_fixed_price > 0 else self.face_value
        t_issue = self.t_issue_to_val + t_from_val
        if self.call_irr <= 0:
            return self.face_value
        return self.face_value * ((1 + self.call_irr) ** t_issue)

    @property
    def has_put(self) -> bool:
        """풋옵션 활성 여부 (IRR 모드: irr>0, 고정 모드: fixed_price>0)"""
        if self.put_start is None:
            return False
        if self.put_price_mode == "fixed":
            return self.put_fixed_price > 0
        return self.put_irr > 0

    @property
    def has_call(self) -> bool:
        """발행자 콜 활성 여부 (IRR 모드: irr>0, 고정 모드: fixed_price>0)"""
        if self.call_start is None:
            return False
        if self.call_price_mode == "fixed":
            return self.call_fixed_price > 0
        return self.call_irr > 0

    def get_kd(self, t_years: float = None) -> float:
        """해당 만기에 대한 채권 할인율 (기간구조 있으면 보간)"""
        if self.yield_curve and t_years is not None:
            return _interp_rate(self.yield_curve, t_years)
        return self.discount_rate

    def is_refixing_date(self, step: int, steps: int) -> bool:
        if not self.refixing:
            return False
        freq = self.refixing_frequency
        if freq == "continuous":
            return True
        dt = self.T / steps
        t = step * dt
        if freq == "quarterly":
            interval = 0.25
        elif freq == "semi-annual":
            interval = 0.5
        elif freq == "annual":
            interval = 1.0
        else:
            return True
        rem = t % interval
        return rem < dt or (interval - rem) < dt


def _interp_rate(curve: List[Tuple[float, float]], t: float) -> float:
    """선형 보간"""
    if t <= curve[0][0]:
        return curve[0][1]
    if t >= curve[-1][0]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        t0, r0 = curve[i]
        t1, r1 = curve[i + 1]
        if t0 <= t <= t1:
            w = (t - t0) / (t1 - t0)
            return r0 + w * (r1 - r0)
    return curve[-1][1]
