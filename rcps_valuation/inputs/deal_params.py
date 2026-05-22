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
    # ── 우선배당 누적성·지급 시점
    # dividend_cumulative=True(누적적): 미지급분이 다음 지급일로 단리 이월·합산
    #   False(비누적적): 미지급분 영구 소멸(이월 없음)
    # dividend_first_pay_year: 실제 첫 배당 지급 시점(발행 후 연수). 0 이면 첫 지급일(=interval)부터 매기 지급.
    #   배당가능이익 가정 시점 — 예) 3 이면 발행 3년차에 첫 지급(누적이면 1~3년차분 일괄)
    dividend_cumulative: bool = True
    dividend_first_pay_year: float = 0.0

    # ── 전환 조건
    conversion_price: float = 0.0    # 전환가액 (원/주)
    conversion_start: Optional[date] = None  # 전환청구 가능 시작일

    # ── 풋옵션 (보유자 상환청구)
    put_start: Optional[date] = None     # 풋 행사 가능 시작일
    put_irr: float = 0.0                 # 행사가 산정 이자율/IRR (연율, 예: 0.075 = 7.5%)
    # 행사가 방식(put_price_mode) — 5803 콜·풋 입력 방식과 동일 체계:
    #   "sp"            단리: face × (1 + r·t)
    #   "cp_y/cp_h/cp_q" 복리(연/반기/분기), 쿠폰 차감 X: face × (1 + r/m)^(m·t)
    #   "irr_y/irr_h/irr_q" 복리 IRR make-whole, 쿠폰 재투자가치 차감
    #   "contract"      계약 비율: face × put_contract_ratio
    #   "fixed"         정액: put_fixed_price
    #   "irr"           (레거시) = irr_y
    #   N/A(행사 불가)는 has_put=False(put_start 미입력)로 표현
    put_price_mode: str = "irr"
    put_fixed_price: float = 0.0         # 고정 풋 행사가액 (정액, 발행금액 스케일)
    # make-whole 쿠폰 차감 기준:
    #   "accrual"(기본, 5803 동일): 연 단위로 발생한 배당 권리를 매기 차감(실제 지급시점 무관)
    #   "actual": 실제 지급된 배당(누적성·첫지급연차 반영)만 차감 — 비누적 소멸분은 차감 안 함
    put_coupon_netting: str = "accrual"
    put_contract_ratio: float = 0.0      # contract 모드: 행사가 = face × 비율

    # ── 콜옵션 (발행자 수의상환권)
    call_start: Optional[date] = None   # 콜 행사 가능 시작일
    call_irr: float = 0.0               # 행사가 산정 이자율/IRR (연율, 예: 0.05 = 5%)
    # 행사가 방식(call_price_mode): put_price_mode 와 동일 체계
    #   sp | cp_y/h/q | irr_y/h/q | contract | fixed
    #   "irr"(레거시) = cp_y (기존 동작: 복리·쿠폰차감X 보존)
    call_price_mode: str = "irr"
    call_fixed_price: float = 0.0       # 고정 콜 행사가액 (정액, 발행금액 스케일)
    call_contract_ratio: float = 0.0    # contract 모드: 행사가 = face × 비율
    call_coupon_netting: str = "accrual"  # irr_* 모드 쿠폰 차감 기준 (accrual|actual)

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
    # refixing_ratchet: 경로의존 래칫(lock-in) 여부.
    #   True(기본)  — 전환가 K가 경로상 최저로 내려가 '유지'(메모리). 진짜 동적 리픽싱.
    #                 recombining 트리(TF/GS)는 경로이력을 못 들고 다녀 과소반영 →
    #                 requires_mc=True 로 MC 전용 평가 라우팅.
    #   False       — spot(메모리 없음). 매 노드 현재주가만으로 재산정(트리 근사). 트리도 사용 가능.
    refixing_ratchet: bool = True
    # VWAP 리픽싱: 리픽싱 기준가를 직전 N스텝 평균(아시안형)으로. 0=spot(현재주가), N>0=평균. (경로의존→MC)
    refixing_vwap_window: int = 0

    # ── 경로의존 배리어 옵션 (전부 주가연동·경로의존 → requires_mc) ──
    # 소프트콜: 발행자 콜이 '주가 ≥ 배리어×전환가'를 (window 중 count회) 충족할 때만 활성 (Parisian)
    call_soft_barrier: Optional[float] = None   # 전환가 대비 배리어 (예 1.30). None=미사용
    call_soft_window: int = 1                    # Parisian 관측 창(스텝). 1=단순배리어
    call_soft_count: int = 1                     # 창 중 충족 필요 횟수. 1=단순배리어
    # 강제전환(Knock-out): '주가 ≥ 배리어×전환가' (window 중 count회) 충족 시 보통주 강제전환 (채권·풋 소멸)
    mandatory_conv_barrier: Optional[float] = None  # 전환가 대비 배리어 (예 2.0). None=미사용
    mandatory_conv_window: int = 1
    mandatory_conv_count: int = 1
    # 배리어 풋(down-and-in): 주가가 '최초주가×배리어' 이하를 한번이라도 터치한 경로에서만 풋 활성
    put_barrier: Optional[float] = None         # 최초주가 S0 대비 배리어 (예 0.50). None=미사용

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
    def _mc_features(self) -> List[str]:
        """켜져 있는 경로의존(MC 전용) 피처 목록."""
        f = []
        if self.refixing and getattr(self, "refixing_ratchet", True):
            f.append("래칫 리픽싱(전환가 경로 최저 lock-in)")
        if self.refixing and getattr(self, "refixing_vwap_window", 0):
            f.append("VWAP 리픽싱(직전 %d스텝 평균기준)" % self.refixing_vwap_window)
        if self.call_soft_barrier:
            f.append("소프트콜 배리어(주가≥전환가×%.2f)" % self.call_soft_barrier)
        if self.mandatory_conv_barrier:
            f.append("강제전환 Knock-out(주가≥전환가×%.2f)" % self.mandatory_conv_barrier)
        if self.put_barrier:
            f.append("배리어 풋 down-and-in(주가≤S₀×%.2f)" % self.put_barrier)
        return f

    @property
    def requires_mc(self) -> bool:
        """경로의존 피처가 켜져 있어 recombining 트리(TF/GS)로는 정확히 평가 불가 →
        MC 전용 라우팅이 필요한지 여부."""
        return len(self._mc_features) > 0

    @property
    def mc_only_reason(self) -> str:
        """requires_mc 사유(사용자 안내용). 없으면 빈 문자열."""
        feats = self._mc_features
        if not feats:
            return ""
        return ("경로의존 옵션이 활성화되어 있습니다 — " + ", ".join(feats) +
                ". 이런 경로의존 효과는 recombining 트리(TF/GS)가 구조적으로 반영하지 못해 "
                "과소평가되므로 MC(몬테카를로) 전용으로 평가합니다.")

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

    def _coupon_interval(self) -> Optional[float]:
        return {"annual": 1.0, "semi": 0.5, "quarterly": 0.25}.get(self.coupon_frequency)

    def dividend_payments_from_issue(self) -> List[Tuple[float, float]]:
        """
        발행일 기준 실제 배당 '지급' 스트림 [(t_from_issue, amount), ...].
        누적성(dividend_cumulative)·첫지급연차(dividend_first_pay_year) 반영.
        _coupon_schedule(트리)와 풋 make-whole(actual 모드)이 공유하는 단일 소스.
          • 누적적: 첫 지급일 전 적립분을 단리 합산해 해당 지급일에 일괄
          • 비누적적: 지급 대상 기간만 1× (그 외 소멸)
        """
        rate = self.coupon_rate
        interval = self._coupon_interval()
        if rate <= 0 or self.coupon_frequency == "none" or not interval:
            return []
        cumulative = getattr(self, "dividend_cumulative", True)
        first_pay_t = max(float(getattr(self, "dividend_first_pay_year", 0.0) or 0.0), 0.0)
        per = self.face_value * rate * interval
        T_total = (self.maturity_date - self.issue_date).days / 365.0
        n = int(round(T_total / interval))
        eps = 1e-9
        payments: List[Tuple[float, float]] = []
        accrued = 0.0
        for k in range(1, n + 1):
            t = k * interval
            if cumulative:
                accrued += per
                if t >= first_pay_t - eps:
                    payments.append((t, accrued))
                    accrued = 0.0
            else:
                if t >= first_pay_t - eps:
                    payments.append((t, per))
        if cumulative and accrued > eps:
            payments.append((n * interval, accrued))
        return payments

    def _exercise_price(self, t_from_val: float, mode: str, rate: float,
                        fixed_price: float, contract_ratio: float,
                        netting: str) -> float:
        """
        행사가 산정 단일 엔진 — 풋·콜 공통. 5803 입력 방식 전부 지원:
          fixed            정액
          contract         face × 비율
          sp               단리   face × (1 + r·t)
          cp_y/cp_h/cp_q   복리(m=1/2/4), 쿠폰 차감 X   face × (1 + r/m)^(m·t)
          irr_y/irr_h/irr_q 복리 IRR make-whole: 위에서 쿠폰 재투자가치를 동일 복리주기로 차감
        t = 발행일→노드 경과연수. 쿠폰 차감(netting): accrual(연 발생) | actual(실제 지급분).
        """
        face = self.face_value
        t = self.t_issue_to_val + t_from_val

        if mode == "fixed":
            return fixed_price if fixed_price > 0 else face
        if mode == "contract":
            return face * contract_ratio if contract_ratio > 0 else face
        if mode == "sp":
            return max(face, face * (1.0 + rate * t))

        if mode in ("cp_y", "cp_h", "cp_q", "irr_y", "irr_h", "irr_q"):
            m = {"y": 1, "h": 2, "q": 4}[mode[-1]]
            base = face * ((1.0 + rate / m) ** (m * t))
            if mode.startswith("cp"):
                return max(face, base)
            # ── irr_*: make-whole 쿠폰 차감 (동일 복리주기 g^(m·Δ))
            interval = self._coupon_interval()
            if rate <= 0 or self.coupon_rate <= 0 or self.coupon_frequency == "none" or not interval:
                return max(face, base)
            g = 1.0 + rate / m
            fv_coupons = 0.0
            if netting == "actual":
                # 실제 지급된 배당(누적성·첫지급연차)만 차감 — 비누적 소멸분 제외
                for t_pay, amt in self.dividend_payments_from_issue():
                    if t_pay <= t + 1e-9:
                        fv_coupons += amt * (g ** (m * (t - t_pay)))
            else:
                # accrual(기본, 5803 동일): 연 단위 발생 배당 권리를 매기 차감
                coupon_amount = face * self.coupon_rate * interval
                j = 1
                while j * interval <= t + 1e-9:
                    fv_coupons += coupon_amount * (g ** (m * (t - j * interval)))
                    j += 1
            return max(face, base - fv_coupons)

        return face  # 알 수 없는 모드 → 액면

    def put_exercise_price(self, t_from_val: float) -> float:
        """노드 시점 풋 행사가액. put_price_mode 체계는 필드 주석 참조. 'irr'(레거시)=irr_y."""
        mode = self.put_price_mode or "irr_y"
        if mode == "irr":
            mode = "irr_y"
        return self._exercise_price(
            t_from_val, mode, self.put_irr, self.put_fixed_price,
            getattr(self, "put_contract_ratio", 0.0),
            getattr(self, "put_coupon_netting", "accrual"))

    def call_exercise_price(self, t_from_val: float) -> float:
        """노드 시점 콜 행사가액. call_price_mode 체계 동일. 'irr'(레거시)=cp_y(기존 동작 보존)."""
        mode = self.call_price_mode or "cp_y"
        if mode == "irr":
            mode = "cp_y"
        return self._exercise_price(
            t_from_val, mode, self.call_irr, self.call_fixed_price,
            getattr(self, "call_contract_ratio", 0.0),
            getattr(self, "call_coupon_netting", "accrual"))

    @property
    def has_put(self) -> bool:
        """풋옵션 활성 여부 (fixed→가격>0, contract→비율>0, sp/cp/irr→rate>0)"""
        if self.put_start is None:
            return False
        mode = self.put_price_mode or "irr_y"
        if mode == "fixed":
            return self.put_fixed_price > 0
        if mode == "contract":
            return getattr(self, "put_contract_ratio", 0.0) > 0
        return self.put_irr > 0

    @property
    def has_call(self) -> bool:
        """발행자 콜 활성 여부 (fixed→가격>0, contract→비율>0, sp/cp/irr→rate>0)"""
        if self.call_start is None:
            return False
        mode = self.call_price_mode or "cp_y"
        if mode == "fixed":
            return self.call_fixed_price > 0
        if mode == "contract":
            return getattr(self, "call_contract_ratio", 0.0) > 0
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
