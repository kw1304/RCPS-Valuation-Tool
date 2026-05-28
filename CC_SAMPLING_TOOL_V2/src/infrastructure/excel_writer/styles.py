"""Excel 서식 토큰 — Phase 4까지 재사용."""
from __future__ import annotations
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


HEADER_FILL = PatternFill("solid", fgColor="1E3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_ALIGN = Alignment(horizontal="center", vertical="center")

BODY_FONT = Font(size=10)
NUM_ALIGN = Alignment(horizontal="right")
TEXT_ALIGN = Alignment(horizontal="left")

_thin = Side(style="thin", color="C0C0C0")
CELL_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


TITLE_FONT = Font(bold=True, size=14, color="1E3A5F")
SUBTITLE_FONT = Font(bold=True, size=11, color="1E3A5F")
META_FONT = Font(size=10)
SIGN_FONT = Font(italic=True, size=10, color="6B7280")
TICKMARK_FONT = Font(bold=True, size=10, color="D4A017")
