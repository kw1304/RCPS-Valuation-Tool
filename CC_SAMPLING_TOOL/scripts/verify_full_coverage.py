"""전원 소명 검증 스크립트 — 50 거래처 소명 상태 리포트.

사용법:
    python scripts/verify_full_coverage.py --project-id <pid>
    python scripts/verify_full_coverage.py --project-id <pid> --threshold 5

출력:
    50 거래처 각각의 상태 및 요약 (unresolved ≤ threshold 합격)

상태 분류:
    matched          — PDF 회신 + 차이 없음
    mismatch         — PDF 회신 + 차이 있음 (추가 확인 필요)
    대체적_충분      — AlternativeProcedure.conclusion == "충분"
    대체적_부분      — AlternativeProcedure.conclusion == "부분"
    대체적_미해소    — AlternativeProcedure.conclusion == "미해소"
    대체적_pending   — AlternativeProcedure 있으나 아직 증빙 미등록 (미회신 placeholder)
    needs_review     — 회신 있으나 추출 실패 또는 수동 검토 필요
    unresolved       — 아무 처리도 없음 (회신도 대체적 절차도 없음)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 프로젝트 루트 경로 등록
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.infrastructure.persistence import (
    AlternativeProcedureRepository,
    ConfirmationReplyRepository,
    ProjectRepository,
    WorkpaperRepository,
    get_session,
)

# 합격 기준: unresolved ≤ 이 값
DEFAULT_THRESHOLD = 5

# AlternativeProcedure conclusion → 사용자 친화 상태명
_CONCLUSION_MAP = {
    "충분": "대체적_충분",
    "부분": "대체적_부분",
    "미해소": "대체적_미해소",
    "needs_review": "대체적_pending",
}


def classify_party(
    party_name: str,
    kind: str,
    ledger_balance: float,
    reply_status: str | None,    # ConfirmationReply.status (가장 좋은 것)
    alt_conclusion: str | None,  # AlternativeProcedure.conclusion
) -> str:
    """거래처 한 건의 소명 상태를 결정한다."""
    # 1. 회신 matched
    if reply_status == "matched":
        return "matched"
    # 2. 회신 mismatch — 차이 있음 (대체적 절차 병행 가능)
    if reply_status == "mismatch":
        if alt_conclusion in ("충분", "부분"):
            return _CONCLUSION_MAP[alt_conclusion]
        return "mismatch"
    # 3. 대체적 절차 결론 있음
    if alt_conclusion:
        return _CONCLUSION_MAP.get(alt_conclusion, "대체적_pending")
    # 4. 회신 있으나 needs_review
    if reply_status == "needs_review":
        return "needs_review"
    # 5. 아무것도 없음
    return "unresolved"


def run(project_id: str, threshold: int = DEFAULT_THRESHOLD) -> int:
    """검증 실행. unresolved 건수 반환."""
    with get_session() as s:
        proj = ProjectRepository(s).get(project_id)
        if proj is None:
            print(f"[ERROR] 프로젝트 {project_id} 없음", file=sys.stderr)
            return -1

        wp_repo = WorkpaperRepository(s)
        reply_repo = ConfirmationReplyRepository(s)
        proc_repo = AlternativeProcedureRepository(s)

        # 채권·채무 양쪽 final_sampled 수집 (중복 제거 — party+kind 단위)
        party_rows: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for chk_kind in ("receivable", "payable"):
            chk_wp = wp_repo.get_or_create(project_id, chk_kind)
            if not chk_wp.sampling_result:
                continue
            for d in json.loads(chk_wp.sampling_result).get("decisions", []):
                if d.get("final_sampled"):
                    key = (d["name"], chk_kind)
                    if key not in seen:
                        seen.add(key)
                        party_rows.append({
                            "name": d["name"],
                            "kind": chk_kind,
                            "balance": float(d.get("balance", 0)),
                            "wp_id": chk_wp.id,
                        })

        total_parties = len(party_rows)
        print(f"\n=== 전원 소명 검증 — {proj.company_name} ({proj.period_end}) ===")
        print(f"총 샘플링 거래처: {total_parties}건\n")

        # 상태별 집계
        status_counts: dict[str, int] = {}
        detail_rows: list[dict] = []

        for row in party_rows:
            pn = row["name"]
            wp_id = row["wp_id"]
            lb = row["balance"]
            chk_kind = row["kind"]

            # 회신 최우선 상태 (matched > mismatch > needs_review > 기타)
            replies = reply_repo.list_by_workpaper(wp_id)
            matched_replies = [r for r in replies if r.party_name_matched == pn]
            best_reply_status: str | None = None
            for priority_status in ("matched", "mismatch", "needs_review"):
                if any(r.status == priority_status for r in matched_replies):
                    best_reply_status = priority_status
                    break

            # AlternativeProcedure
            proc = proc_repo.get_by_party(wp_id, pn)
            alt_conclusion = proc.conclusion if proc else None

            status = classify_party(pn, chk_kind, lb, best_reply_status, alt_conclusion)
            status_counts[status] = status_counts.get(status, 0) + 1

            detail_rows.append({
                "party": pn,
                "kind": "채권" if chk_kind == "receivable" else "채무",
                "balance": lb,
                "status": status,
                "reply": best_reply_status or "-",
                "alt_conclusion": alt_conclusion or "-",
            })

        # 상세 출력
        print(f"{'거래처':<30} {'구분':<5} {'장부가(원)':>15} {'상태':<16} {'회신':<12} {'대체절차결론'}")
        print("-" * 95)
        for dr in sorted(detail_rows, key=lambda x: (x["status"], x["kind"], x["party"])):
            print(
                f"{dr['party']:<30} {dr['kind']:<5} "
                f"{dr['balance']:>15,.0f} {dr['status']:<16} "
                f"{dr['reply']:<12} {dr['alt_conclusion']}"
            )

        # 요약
        print("\n=== 상태 요약 ===")
        for status_name in ["matched", "mismatch", "대체적_충분", "대체적_부분",
                             "대체적_미해소", "대체적_pending", "needs_review", "unresolved"]:
            cnt = status_counts.get(status_name, 0)
            if cnt:
                print(f"  {status_name:<20}: {cnt}건")

        unresolved = status_counts.get("unresolved", 0)
        needs_review = status_counts.get("needs_review", 0)
        total_unresolved = unresolved + needs_review

        print(f"\n총 unresolved (unresolved + needs_review): {total_unresolved}건")
        if total_unresolved <= threshold:
            print(f"[PASS] 합격선 ≤ {threshold}건 충족")
        else:
            print(f"[FAIL] 합격선 초과 ({total_unresolved} > {threshold}건)")

        return total_unresolved


def main() -> None:
    parser = argparse.ArgumentParser(description="전원 소명 검증 스크립트")
    parser.add_argument("--project-id", required=True, help="프로젝트 ID")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"unresolved 합격선 (기본: {DEFAULT_THRESHOLD})")
    args = parser.parse_args()

    result = run(args.project_id, args.threshold)
    sys.exit(0 if result <= args.threshold else 1)


if __name__ == "__main__":
    main()
