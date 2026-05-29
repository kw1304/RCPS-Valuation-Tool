"""번호 섹션 헤더 앵커로 텍스트를 구역별로 분할.

헤더 라인("N. ...다음과 같습니다")을 경계로, 헤더 다음 줄부터
다음 헤더 전까지를 그 섹션 번호의 블록으로 모은다.
라인 단위 키워드 추측(구 section_classifier)을 대체 — drift 없음.
"""
import re

_HEADER = re.compile(r"^\s*(\d{1,2})\.\s*.{6,90}?(?:습니다|입니다)")


def split_sections(text: str) -> dict[int, str]:
    blocks: dict[int, list[str]] = {}
    current: int | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = _HEADER.match(s)
        if m:
            current = int(m.group(1))
            blocks.setdefault(current, [])
            continue
        if current is not None:
            blocks[current].append(s)
    return {k: "\n".join(v) for k, v in blocks.items() if v}
