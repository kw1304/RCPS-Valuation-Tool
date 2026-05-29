from pathlib import Path
import pdfplumber


def extract_text_and_tables(path: Path) -> dict:
    """
    Digital PDF 우선 시도. 실패 시 OCR fallback (별도 호출자가 처리).

    Args:
        path: PDF 파일 경로

    Returns:
        dict with keys:
            - text: 추출된 텍스트 (페이지별로 개행으로 구분)
            - tables: 추출된 테이블 목록 (각 테이블은 list[list[str]])
            - pages: 텍스트가 추출된 페이지 수
    """
    text_parts: list[str] = []
    tables: list[list[list]] = []

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                text_parts.append(t)
            for tab in (page.extract_tables() or []):
                tables.append(tab)

    return {
        "text": "\n".join(text_parts),
        "tables": tables,
        "pages": len(text_parts),
    }


# 한 논리 행으로 묶을 단어들의 수직(top) 허용 오차(px).
# 국민은행 ground truth로 튜닝: 9px이면 줄바꿈된 금액(126,598,004 / 308,755 /
# 1,500,000)이 라벨 행과 재결합되면서도, 인접한 서로 다른 계좌 행은 병합되지
# 않는다. 11px 이상이면 위 행의 잔여 조각("예금")이 아래 계좌 행에 붙어버린다.
_ROW_TOL = 9.0


def extract_rows(path: Path) -> str:
    """좌표 기반 논리 행 재구성.

    무테(borderless) 회신서 표는 금액이 라벨과 다른 물리 라인으로 줄바꿈되어
    page.extract_text()의 평면 텍스트에서 금액이 라벨과 분리·유실된다.
    여기서는 extract_words()의 단어 좌표(top/x0)를 사용해 수직 위치가
    가까운 단어들을 하나의 논리 행으로 묶고, 행 내부는 x0(좌→우)로 정렬해
    "퇴직연금 ... 126,598,004.00 ..." 같은 참 논리 행을 복원한다.

    각 페이지:
      - extract_words(use_text_flow=False, keep_blank_chars=False)
      - top 기준 정렬 후, 클러스터 첫 단어의 top을 앵커로 _ROW_TOL 이내 단어를
        같은 행에 모은다(앵커 고정 → drift 방지).
      - 행 내부는 x0로 정렬 후 단일 공백으로 join.
    페이지는 개행으로 연결.
    """
    out_lines: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(
                use_text_flow=False, keep_blank_chars=False
            ) or []
            if not words:
                continue
            words.sort(key=lambda w: (w["top"], w["x0"]))
            cluster: list[dict] = []
            anchor_top: float | None = None
            for w in words:
                if anchor_top is None or abs(w["top"] - anchor_top) <= _ROW_TOL:
                    if anchor_top is None:
                        anchor_top = w["top"]
                    cluster.append(w)
                else:
                    out_lines.append(_join_cluster(cluster))
                    cluster = [w]
                    anchor_top = w["top"]
            if cluster:
                out_lines.append(_join_cluster(cluster))
    return "\n".join(out_lines)


def _join_cluster(cluster: list[dict]) -> str:
    cluster.sort(key=lambda w: w["x0"])
    return " ".join(w["text"] for w in cluster)
