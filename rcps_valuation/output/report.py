from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime


def generate_workpaper(params, initial_result, subsequent_results, sensitivity_result, output_path, tf_tree=None, gs_tree=None):
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "1.발행조건"
    _write_cover(ws1, params, initial_result)

    ws2 = wb.create_sheet("2.평가결과")
    _write_valuation(ws2, initial_result)

    # 이항트리 시트 (TF/GS, collect_tree 결과 있을 때만)
    if tf_tree and not tf_tree.get("error"):
        ws_tf = wb.create_sheet("3.TF이항트리")
        _write_tree(ws_tf, "TF (Tsiveriotis-Fernandes)", tf_tree)
    if gs_tree and not gs_tree.get("error"):
        ws_gs = wb.create_sheet("4.GS이항트리")
        _write_tree(ws_gs, "GS (Goldman Sachs)", gs_tree)

    if subsequent_results:
        ws_sub = wb.create_sheet("5.후속측정")
        _write_subsequent(ws_sub, subsequent_results)

    ws_sens = wb.create_sheet("6.민감도분석")
    _write_sensitivity(ws_sens, sensitivity_result)

    wb.save(output_path)
    return output_path


def _write_tree(ws, title, tree):
    """이항트리 그리드 출력. tree = {stock, rcps_value, conv_intrinsic, decision, u, d, p, steps}"""
    stock = tree.get("stock") or []
    rcps  = tree.get("rcps_value") or []
    conv  = tree.get("conv_intrinsic") or []
    dec   = tree.get("decision") or []
    n = len(stock)
    if n == 0:
        return
    steps = tree.get("steps", n - 1)
    u = tree.get("u"); d = tree.get("d"); p = tree.get("p")

    # 타이틀
    ws.row_dimensions[1].height = 32
    t = ws.cell(row=1, column=1, value=f"이항트리 — {title}")
    t.font = Font(name="맑은 고딕", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(fill_type="solid", fgColor="1A365D")
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=min(n + 1, 10))

    # 트리 파라미터
    ws.cell(row=2, column=1, value=f"steps={steps} | u={u} | d={d} | p={p if not isinstance(p,list) else 'curve'}").font = Font(name="맑은 고딕", size=9, color="718096")

    # 컬럼 폭
    for c in range(1, n + 2):
        ws.column_dimensions[get_column_letter(c)].width = 14
    ws.column_dimensions["A"].width = 18

    # 4개 블록: 주가 / RCPS가치 / 전환내재 / 의사결정
    def _block(start_row, label, grid, fmt):
        r0 = start_row
        c = ws.cell(row=r0, column=1, value=f"■ {label}")
        c.font = Font(name="맑은 고딕", bold=True, size=11, color="1A365D")
        # 헤더: 노드 j (0..steps)
        _hdr(ws, r0 + 1, 1, "Step \\ j")
        for j in range(n):
            _hdr(ws, r0 + 1, j + 2, f"j={j}")
        for i in range(n):
            _hdr(ws, r0 + 2 + i, 1, f"i={i}")
            row = grid[i] if i < len(grid) else []
            for j in range(i + 1):
                v = row[j] if j < len(row) else None
                if v is None or v == "":
                    _cell(ws, r0 + 2 + i, j + 2, "", bg="FFFFFF")
                else:
                    bg = "F7FAFC" if (i + j) % 2 == 0 else "FFFFFF"
                    if fmt == "money":
                        _cell(ws, r0 + 2 + i, j + 2, v, bg=bg, num_fmt="#,##0.00", align="right")
                    elif fmt == "text":
                        bg2 = {"전환": "C6F6D5", "상환": "FED7D7", "콜": "FEEBC8", "보유": bg}.get(v, bg)
                        _cell(ws, r0 + 2 + i, j + 2, v, bg=bg2, align="center")
                    else:
                        _cell(ws, r0 + 2 + i, j + 2, v, bg=bg, align="right")
        return r0 + 2 + n  # 다음 블록 시작 row 반환

    next_row = _block(4, "주가 (S_{i,j})", stock, "money")
    next_row = _block(next_row + 2, "RCPS 가치 (V_{i,j})", rcps, "money")
    next_row = _block(next_row + 2, "전환 내재가치 (Conv intrinsic)", conv, "money")
    if dec:
        _block(next_row + 2, "의사결정 (Decision: 전환/상환/보유/콜)", dec, "text")


def _cell(ws, row, col, value, bold=False, bg=None, num_fmt=None, align="left", color=None):
    cell = ws.cell(row=row, column=col, value=value)
    font_kwargs = dict(name="맑은 고딕", bold=bold, size=10)
    if color:
        font_kwargs["color"] = color
    cell.font = Font(**font_kwargs)
    if bg:
        cell.fill = PatternFill(fill_type="solid", fgColor=bg)
    if num_fmt:
        cell.number_format = num_fmt
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=False)
    side = Side(style="thin", color="DDDDDD")
    cell.border = Border(left=side, right=side, top=side, bottom=side)
    return cell


def _hdr(ws, row, col, value):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(name="맑은 고딕", bold=True, size=10, color="FFFFFF")
    c.fill = PatternFill(fill_type="solid", fgColor="1A365D")
    c.alignment = Alignment(horizontal="center", vertical="center")
    side = Side(style="thin", color="FFFFFF")
    c.border = Border(left=side, right=side, top=side, bottom=side)
    return c


def _write_cover(ws, params, initial):
    for col, w in zip("ABCD", [26, 22, 20, 20]):
        ws.column_dimensions[col].width = w
    ws.row_dimensions[1].height = 36

    t = ws.cell(row=1, column=1, value="상환전환우선주(RCPS) 공정가치 평가 조서")
    t.font = Font(name="맑은 고딕", bold=True, size=14, color="FFFFFF")
    t.fill = PatternFill(fill_type="solid", fgColor="1A365D")
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:D1")

    ws.cell(row=2, column=1, value=f"작성일: {datetime.today().strftime('%Y-%m-%d')}").font = Font(name="맑은 고딕", size=9, color="718096")
    ws.cell(row=2, column=3, value=f"평가기준일: {params.valuation_date}").font = Font(name="맑은 고딕", size=9, color="718096")

    ws.cell(row=4, column=1, value="■ 발행 조건").font = Font(name="맑은 고딕", bold=True, size=11)
    for i, h in enumerate(["항목", "내용", "항목", "내용"], 1):
        _hdr(ws, 5, i, h)

    issue_rows = [
        ("발행일", str(params.issue_date), "만기일", str(params.maturity_date)),
        ("발행금액", f"{params.face_value:,.0f} 원", "보장수익률(IRR)", f"{params.put_irr*100:.2f}%"),
        ("전환가액", f"{params.conversion_price:,.0f} 원/주", "우선배당률", f"{params.coupon_rate*100:.1f}%"),
        ("전환청구시작", str(params.conversion_start), "리픽싱여부", "있음" if params.refixing else "없음"),
    ]
    if params.refixing:
        issue_rows.append(("리픽싱 하한", f"{params.refixing_floor*100:.0f}%", "리픽싱 트리거", f"{params.refixing_trigger*100:.0f}%"))

    for ri, row_data in enumerate(issue_rows, 6):
        bg = "F7FAFC" if ri % 2 == 0 else "FFFFFF"
        for ci, val in enumerate(row_data, 1):
            _cell(ws, ri, ci, val, bg=bg)

    r = 6 + len(issue_rows) + 2
    ws.cell(row=r, column=1, value="■ 시장 데이터 (평가기준일)").font = Font(name="맑은 고딕", bold=True, size=11)
    for i, h in enumerate(["항목", "내용", "항목", "내용"], 1):
        _hdr(ws, r + 1, i, h)

    mkt_rows = [
        ("주가", f"{params.stock_price:,.0f} 원", "잔존기간", f"{initial['key_inputs']['time_to_maturity']:.4f}년"),
        ("변동성(연환산)", f"{params.volatility*100:.1f}%", "무위험이자율", f"{params.risk_free_rate*100:.2f}%"),
        ("신용스프레드", f"{params.credit_spread*100:.2f}%", "할인율(합계)", f"{params.discount_rate*100:.2f}%"),
    ]
    for ri, row_data in enumerate(mkt_rows, r + 2):
        bg = "F7FAFC" if ri % 2 == 0 else "FFFFFF"
        for ci, val in enumerate(row_data, 1):
            _cell(ws, ri, ci, val, bg=bg)


def _write_valuation(ws, initial):
    for col, w in zip("ABC", [30, 24, 14]):
        ws.column_dimensions[col].width = w
    ws.row_dimensions[1].height = 32

    t = ws.cell(row=1, column=1, value="평가 결과")
    t.font = Font(name="맑은 고딕", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(fill_type="solid", fgColor="1A365D")
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:C1")

    for i, h in enumerate(["항목", "금액 (원)", "비율"], 1):
        _hdr(ws, 3, i, h)

    fv = initial["fair_value"]
    straight = initial["straight_bond_value"]
    conv = initial["conversion_component"]

    rows = [
        ("공정가치 (FV)", fv, "100.0%"),
        ("  ├ 순채권가치 (Straight Bond)", straight, f"{straight/fv*100:.1f}%"),
        ("  └ 전환권 가치 (Conversion)", conv, f"{conv/fv*100:.1f}%"),
    ]
    for ri, (label, val, pct) in enumerate(rows, 4):
        bold = ri == 4
        bg = "EBF8FF" if ri == 4 else ("F7FAFC" if ri % 2 == 0 else "FFFFFF")
        _cell(ws, ri, 1, label, bold=bold, bg=bg)
        _cell(ws, ri, 2, val, bold=bold, bg=bg, num_fmt="#,##0", align="right")
        _cell(ws, ri, 3, pct, bg=bg, align="center")

    ws.cell(row=9, column=1, value="■ 모델 정보").font = Font(name="맑은 고딕", bold=True, size=11)
    for i, h in enumerate(["항목", "내용"], 1):
        _hdr(ws, 10, i, h)

    model_rows = [
        ("평가모형", initial["model"]),
        ("트리 단계수", str(initial["steps"])),
        ("위험중립확률 (p)", f"{initial['binomial_detail']['risk_neutral_prob']:.4f}"),
        ("채권 할인율", f"{initial['binomial_detail']['discount_rate']*100:.2f}%"),
        ("상승배수 (u)", f"{initial['binomial_detail']['u']:.6f}"),
        ("하락배수 (d)", f"{initial['binomial_detail']['d']:.6f}"),
    ]
    for ri, (k, v) in enumerate(model_rows, 11):
        bg = "F7FAFC" if ri % 2 == 0 else "FFFFFF"
        _cell(ws, ri, 1, k, bg=bg)
        _cell(ws, ri, 2, v, bg=bg)


def _write_subsequent(ws, results):
    cols = ["A", "B", "C", "D", "E", "F", "G", "H"]
    widths = [14, 20, 20, 18, 18, 12, 14, 12]
    for col, w in zip(cols, widths):
        ws.column_dimensions[col].width = w
    ws.row_dimensions[1].height = 32

    t = ws.cell(row=1, column=1, value="후속측정 — 보고기간별 공정가치")
    t.font = Font(name="맑은 고딕", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(fill_type="solid", fgColor="1A365D")
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:H1")

    headers = ["평가기준일", "공정가치(원)", "순채권가치(원)", "전환권가치(원)", "변동액(원)", "변동률", "주가(원)", "변동성"]
    for i, h in enumerate(headers, 1):
        _hdr(ws, 3, i, h)

    for ri, row in enumerate(results, 4):
        bg = "F7FAFC" if ri % 2 == 0 else "FFFFFF"
        chg = row["change"]
        chg_bg = "C6F6D5" if chg and chg > 0 else ("FED7D7" if chg and chg < 0 else bg)

        _cell(ws, ri, 1, row["date"], bg=bg, align="center")
        _cell(ws, ri, 2, row["fair_value"], bg=bg, num_fmt="#,##0", align="right")
        _cell(ws, ri, 3, row["straight_bond_value"], bg=bg, num_fmt="#,##0", align="right")
        _cell(ws, ri, 4, row["conversion_component"], bg=bg, num_fmt="#,##0", align="right")
        _cell(ws, ri, 5, chg if chg is not None else "-", bg=chg_bg, num_fmt="#,##0", align="right")
        _cell(ws, ri, 6, f"{row['change_pct']:+.2f}%" if row["change_pct"] is not None else "-", bg=chg_bg, align="center")
        _cell(ws, ri, 7, row["stock_price"], bg=bg, num_fmt="#,##0", align="right")
        _cell(ws, ri, 8, f"{row['volatility']}%", bg=bg, align="center")


def _write_sensitivity(ws, sensitivity):
    for col, w in zip("ABCDEFG", [14, 20, 12, 4, 14, 20, 12]):
        ws.column_dimensions[col].width = w
    ws.row_dimensions[1].height = 32

    t = ws.cell(row=1, column=1, value="민감도 분석")
    t.font = Font(name="맑은 고딕", bold=True, size=13, color="FFFFFF")
    t.fill = PatternFill(fill_type="solid", fgColor="1A365D")
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:G1")

    base_fv = sensitivity["base_fair_value"]
    ws.cell(row=2, column=1, value=f"기준 공정가치: {base_fv:,.0f} 원").font = Font(name="맑은 고딕", bold=True, size=10)

    def _sens_block(start_row, start_col, title, data, col_label):
        ws.cell(row=start_row, column=start_col, value=f"■ {title}").font = Font(name="맑은 고딕", bold=True, size=11)
        for i, h in enumerate([col_label, "공정가치(원)", "변동률"], 1):
            _hdr(ws, start_row + 1, start_col + i - 1, h)
        for ri, row in enumerate(data, start_row + 2):
            bg = "EBF8FF" if abs(row["change_pct"]) < 0.5 else ("F7FAFC" if ri % 2 == 0 else "FFFFFF")
            chg_bg = "C6F6D5" if row["change_pct"] > 0 else ("FED7D7" if row["change_pct"] < 0 else bg)
            _cell(ws, ri, start_col, row["label"], bg=bg, align="center")
            _cell(ws, ri, start_col + 1, row["fair_value"], bg=bg, num_fmt="#,##0", align="right")
            _cell(ws, ri, start_col + 2, f"{row['change_pct']:+.2f}%", bg=chg_bg, align="center")

    _sens_block(4, 1, "변동성 민감도", sensitivity["volatility"], "변동성")
    _sens_block(4, 5, "주가 민감도", sensitivity["stock_price"], "주가(원)")

    offset = max(len(sensitivity["volatility"]), len(sensitivity["stock_price"])) + 7
    _sens_block(offset, 1, "신용스프레드 민감도", sensitivity["credit_spread"], "신용스프레드")
