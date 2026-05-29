"""번호 섹션 헤더 앵커로 텍스트를 구역별로 분할.

헤더 라인("N. ...다음과 같습니다")을 경계로, 헤더 다음 줄부터
다음 헤더 전까지를 그 섹션 번호의 블록으로 모은다.
라인 단위 키워드 추측(구 section_classifier)을 대체 — drift 없음.

헤더 문장이 길어 "습니다/입니다"가 다음 1~2 물리 라인으로 줄바꿈되는
경우(예: §9 담보·보증)도 인식한다. 줄바꿈 헤더의 연속 라인은 데이터로
새지 않도록 소비(skip)한다.
"""
import re

# 단일 라인 빠른 경로 (기존 동작 유지)
_HEADER = re.compile(r"^\s*(\d{1,2})\.\s*.{6,90}?(?:습니다|입니다)")
# 번호-점으로 시작하는 후보 라인
_NUM_START = re.compile(r"^\s*(\d{1,2})\.\s")
# 줄바꿈 헤더 판정용 (조인된 문자열에 적용, 더 넉넉한 길이 허용)
_HEADER_JOINED = re.compile(r"^\s*(\d{1,2})\.\s.{6,200}?(?:습니다|입니다)")

# 헤더 연속 라인을 lookahead 할 최대 물리 라인 수
_LOOKAHEAD = 2


def split_sections(text: str) -> dict[int, str]:
    # 빈 라인 제거 후 라인 리스트화 (lookahead 인덱싱 위함)
    lines = [s for ln in text.splitlines() if (s := ln.strip())]

    blocks: dict[int, list[str]] = {}
    current: int | None = None
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i]

        # 1) 단일 라인 빠른 경로
        m = _HEADER.match(s)
        if m:
            current = int(m.group(1))
            blocks.setdefault(current, [])
            i += 1
            continue

        # 2) 줄바꿈 헤더: 번호-점 시작이지만 같은 줄에서 종결어가 안 나온 경우
        if _NUM_START.match(s):
            joined = s
            consumed_upto = None  # 헤더 종결(습니다/입니다)을 포함한 마지막 라인 인덱스
            for j in range(1, _LOOKAHEAD + 1):
                if i + j >= n:
                    break
                nxt = lines[i + j]
                # 다음 라인이 또 다른 번호-점 헤더면 lookahead 중단 (다른 섹션 침범 방지)
                if _NUM_START.match(nxt):
                    break
                joined = joined + " " + nxt
                if _HEADER_JOINED.match(joined):
                    consumed_upto = i + j
                    break
            if consumed_upto is not None:
                hm = _HEADER_JOINED.match(joined)
                current = int(hm.group(1))
                blocks.setdefault(current, [])
                # 헤더 문장을 구성한 연속 라인까지 소비 (데이터 오염 방지)
                i = consumed_upto + 1
                continue
            # 헤더로 해석 못하면 일반 데이터로 처리 (오분류 방지)

        # 3) 일반 데이터 라인
        if current is not None:
            blocks[current].append(s)
        i += 1

    return {k: "\n".join(v) for k, v in blocks.items() if v}
