# 웅계사's CC Sampling Tool

채권채무조회서(AR/AP Confirmation) **MUS 표본추출** 자동화 툴.

## 근거 기준
- **감사기준서 530** (표본감사)
- **AICPA Audit Guide — Audit Sampling**
- K-IFRS 1109/1115 잔액 평가는 본 툴 범위 외 (실재성·완전성 경영진 주장 검토용)

## 처리 흐름
```
[회사 제시 거래처별 원장] + [재무제표]
        ↓
1. 모집단 완전성 검토 (회사명세서 ↔ 재무제표 대사)
2. 발송제외 조정 (예: 채권성격 아닌 항목)
3. 수행중요성(PM) 산출 → Key item 기준금액
4. Key item 추출 (잔액 ≥ 기준금액 전수)
5. Representative sample 추출 (MUS)
        ↓
[조서: C100-1/2/3 + AA100 시트]
```

## 핵심 파라미터
| 항목 | 산식·범위 |
|---|---|
| 수행중요성 PM | 총자산 × 0.5% × 85% (실무 예시) |
| Key item 기준금액 | PM × 비율 (위험·통제의존 매트릭스 25~100%) |
| Confidence Factor | 위험·통제 매트릭스 (0.7 ~ 3.0) |
| Base sample size | (모집단 - Key item) / PM |
| Final sample size | ceil(Base × CF) |
| 표본간격 | 잔여모집단 / Final sample size |
| 임의출발점 | Randbetween(0, 표본간격) |

## 폴더
- `input/조서/` — 기존 조서 (참조용)
- `input/회사자료/` — 회사 제시 거래처별 원장 + 재무제표
- `output/` — 생성된 조서
- `src/` — 엔진·UI 코드
- `templates/` — 조서 템플릿
