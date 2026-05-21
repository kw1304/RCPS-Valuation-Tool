import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, send_file, send_from_directory
from datetime import date, datetime, timedelta
import tempfile, traceback, json
import urllib.request
import csv, io, re
import openpyxl

import numpy as np

from inputs.deal_params import RCPSParams
from inputs.dcf import DCFParams, dcf_valuation
from models.tsiveriotis_fernandes import tf_rcps
from models.goldman_sachs import gs_rcps
from models.monte_carlo import monte_carlo_rcps
from sensitivity.analysis import sensitivity_analysis
from output.report import generate_workpaper

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app = Flask(__name__, static_folder=FRONTEND_DIR)


def _d(s):
    return date.fromisoformat(s) if s else None

def _f(v, default=None):
    try:
        return float(v) if v not in (None, "", "null") else default
    except Exception:
        return default


def _spot_to_step_forwards(spot_pts, T, steps):
    """
    선형보간(linear-on-spot) + 평탄 외삽 → 스텝별 연속 forward rate.

    spot_pts : list of [t_years, z_continuous_decimal]  (z = 연속 스팟)
    T        : 총 기간(년),  steps : 등간격 스텝 수

    - 연속 스팟 z(t)를 만기 사이 선형보간, 최단물 미만/최장물 초과는 평탄 외삽
    - 스텝 i (t1=i·dt, t2=(i+1)·dt): f_i = (z(t2)·t2 − z(t1)·t1)/(t2−t1)
    Returns list of length `steps`, or None on invalid input. Never raises.
    """
    try:
        if not spot_pts or steps <= 0 or T <= 0:
            return None
        # parse and filter valid points (t > 0, z not None)
        raw = []
        for pt in spot_pts:
            try:
                t_yr, z_c = float(pt[0]), float(pt[1])
                if t_yr is not None and z_c is not None and t_yr > 0:
                    raw.append((t_yr, z_c))
            except (TypeError, ValueError, IndexError):
                continue
        if not raw:
            return None
        raw.sort(key=lambda x: x[0])

        t_last, z_last = raw[-1]

        def zget(t):
            """연속 스팟 선형보간(linear-on-spot) + 평탄 외삽(flat extrapolation)"""
            if t <= raw[0][0]:
                return raw[0][1]
            if t >= t_last:
                return z_last
            for k in range(len(raw) - 1):
                t0, z0 = raw[k]
                t1, z1 = raw[k + 1]
                if t0 <= t <= t1:
                    w = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                    return z0 + w * (z1 - z0)
            return z_last

        dt = T / steps
        out = []
        for i in range(steps):
            t1 = i * dt
            t2 = (i + 1) * dt
            za = zget(t1)
            zb = zget(t2)
            span = t2 - t1
            # forward = (z2·t2 − z1·t1)/(t2−t1) ; t1=0 이면 f0 = z2
            f_i = (zb * t2 - za * t1) / span if span > 0 else zb
            out.append(f_i)
        return out
    except Exception:
        return None


def parse_params(data: dict) -> RCPSParams:
    return RCPSParams(
        issue_date=_d(data["issue_date"]),
        maturity_date=_d(data["maturity_date"]),
        face_value=float(data["face_value"]),
        coupon_rate=float(data.get("coupon_rate", 0)),
        coupon_frequency=data.get("coupon_frequency", "annual"),
        conversion_price=float(data.get("conversion_price", 0)),
        conversion_start=_d(data.get("conversion_start")),
        put_start=_d(data.get("put_start")),
        put_irr=float(data.get("put_irr", 0)),
        put_price_mode=data.get("put_price_mode", "irr"),
        put_fixed_price=float(data.get("put_fixed_price", 0) or 0),
        call_start=_d(data.get("call_start")),
        call_irr=float(data.get("call_irr", 0)),
        call_price_mode=data.get("call_price_mode", "irr"),
        call_fixed_price=float(data.get("call_fixed_price", 0) or 0),
        refixing=bool(data.get("refixing", False)),
        refixing_floor=_f(data.get("refixing_floor")),
        refixing_trigger=_f(data.get("refixing_trigger")),
        refixing_frequency=data.get("refixing_frequency", "continuous"),
        stock_price=float(data.get("stock_price", 0)),
        volatility=float(data.get("volatility", 0)),
        risk_free_rate=float(data.get("risk_free_rate", 0)),
        credit_spread=float(data.get("credit_spread", 0)),
        dividend_yield=float(data.get("dividend_yield", 0)),
        valuation_date=_d(data["valuation_date"]),
        is_unlisted=bool(data.get("is_unlisted", False)),
    )


def serialize(obj):
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize(i) for i in obj]
    return obj


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/dcf", methods=["POST"])
def dcf():
    try:
        data = request.json
        params = DCFParams(
            fcf_projections=[float(x) for x in data["fcf_projections"]],
            wacc=float(data["wacc"]),
            terminal_growth=float(data.get("terminal_growth", 0.02)),
            net_debt=float(data.get("net_debt", 0)),
            total_shares=float(data.get("total_shares", 1)),
            non_operating_assets=float(data.get("non_operating_assets", 0)),
        )
        result = dcf_valuation(params)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    try:
        data = request.json
        params = parse_params(data["params"])
        steps_req = int(data.get("steps", 0)) or None
        steps_used = steps_req if steps_req else max(int(round(params.T * 12)), 12)

        # 이항 파라미터 (u/d/p) — 프론트 참고용
        dt = params.T / steps_used
        u = float(np.exp(params.volatility * np.sqrt(dt)))
        d = 1.0 / u
        p_rn = float((np.exp((params.risk_free_rate - params.dividend_yield) * dt) - d) / (u - d))

        # ── 선도이자율 커브 (term structure, optional)
        rf_curve = None
        kd_curve = None
        try:
            rf_spot = data.get("rf_spot")
            rd_spot = data.get("rd_spot")
            if rf_spot and rd_spot:
                rf_curve = _spot_to_step_forwards(rf_spot, params.T, steps_used)
                kd_curve = _spot_to_step_forwards(rd_spot, params.T, steps_used)
        except Exception:
            rf_curve = None
            kd_curve = None

        # ── TF 모형 (메인 1)
        try:
            # GS params 에 주식수가 있으면 TF 희석경로도 활성화
            if data.get("gs_params"):
                gp = data["gs_params"]
                cs = _f(gp.get("common_shares"))
                rs = _f(gp.get("rcps_shares"))
                if cs:
                    params.common_shares = cs
                if rs:
                    params.rcps_shares = rs
            tf_kw = {"bond_discrete": False}  # 연속복리: 연속스팟 부트스트랩과 정합 (C-DF=exp(-z·t))
            if rf_curve and kd_curve:
                tf_kw["rf_curve"] = rf_curve
                tf_kw["kd_curve"] = kd_curve
            tf = tf_rcps(params, steps=steps_used, **tf_kw)
            steps_used = tf["steps"]
        except Exception as e:
            tf = {"error": str(e)}

        # ── GS 모형 (메인 2)
        try:
            gs_kw = {"bond_discrete": False}  # 연속복리 (연속스팟 정합)
            if data.get("gs_params"):
                gp = data["gs_params"]
                for k in ("enterprise_value", "net_debt", "common_shares", "rcps_shares"):
                    v = _f(gp.get(k))
                    if v:
                        gs_kw[k] = v
            gs_steps = min(steps_used, 150)
            if rf_curve and kd_curve:
                # GS may use a different step count; rebuild curves if needed
                try:
                    if gs_steps != steps_used:
                        gs_kw["rf_curve"] = _spot_to_step_forwards(
                            data.get("rf_spot"), params.T, gs_steps)
                        gs_kw["kd_curve"] = _spot_to_step_forwards(
                            data.get("rd_spot"), params.T, gs_steps)
                    else:
                        gs_kw["rf_curve"] = rf_curve
                        gs_kw["kd_curve"] = kd_curve
                except Exception:
                    pass
            gs = gs_rcps(params, steps=gs_steps, **gs_kw)
        except Exception as e:
            gs = {"error": str(e)}

        # ── GS 분해 (5803 방식): 채권·풋옵션은 모형 무관 공통값(TF 산출),
        #     GS 전환권 = GS 총액 − 풋채권가치(=채권+풋)
        if (isinstance(gs, dict) and not gs.get("error")
                and isinstance(tf, dict) and not tf.get("error")
                and gs.get("fair_value") is not None
                and tf.get("put_bond_value") is not None):
            pbv = tf["put_bond_value"]
            gs["bond_value"] = tf.get("bond_value")
            gs["put_bond_value"] = pbv
            gs["put_option_value"] = tf.get("put_option_value")
            gs["conversion_value"] = round(gs["fair_value"] - pbv)

        # ── 몬테카를로 (참고)
        try:
            n_paths = int(data.get("mc_paths", 10000))
            mc = monte_carlo_rcps(params, n_paths=n_paths, n_steps=min(steps_used, 260))
        except Exception as e:
            mc = {"error": str(e)}

        # ── 민감도 (TF 기준)
        try:
            sens = sensitivity_analysis(params, steps=min(steps_used, 60))
        except Exception as e:
            sens = {"error": str(e)}

        # ── 후속측정
        subsequent = []
        if data.get("reporting_dates"):
            from valuation.subsequent import subsequent_measurement
            rd = []
            for e in data["reporting_dates"]:
                rd.append({
                    "date": date.fromisoformat(e["date"]),
                    "stock_price": float(e["stock_price"]),
                    "volatility": float(e["volatility"]),
                    "risk_free_rate": float(e.get("risk_free_rate", params.risk_free_rate)),
                    "credit_spread": float(e.get("credit_spread", params.credit_spread)),
                })
            subsequent = subsequent_measurement(params, rd, steps=60)

        result = {
            "tf": tf,
            "gs": gs,
            "mc": mc,
            "sensitivity": sens,
            "steps": steps_used,
            "time_to_maturity": round(params.T, 4),
            "u": round(u, 6),
            "d": round(d, 6),
            "risk_neutral_prob": round(p_rn, 6),
            "term_structure_applied": bool(rf_curve and kd_curve),
        }

        return jsonify({
            "status": "ok",
            "result": serialize(result),
            "subsequent": subsequent,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 400


@app.route("/api/tree", methods=["POST"])
def tree():
    try:
        data = request.json
        params = parse_params(data["params"])

        # propagate share counts from gs_params (same as /api/evaluate)
        if data.get("gs_params"):
            gp = data["gs_params"]
            cs = _f(gp.get("common_shares"))
            rs = _f(gp.get("rcps_shares"))
            if cs:
                params.common_shares = cs
            if rs:
                params.rcps_shares = rs

        # tree step count: caller-supplied (up to 520) or default monthly capped at 120
        tree_steps = data.get("steps")
        if tree_steps is not None:
            try:
                tree_steps = max(1, min(int(tree_steps), 520))
            except (TypeError, ValueError):
                tree_steps = None
        if not tree_steps:
            tree_steps = min(round(params.T * 12), 120)
            tree_steps = max(1, tree_steps)

        # ── 선도이자율 커브 (term structure, optional)
        tree_rf_curve = None
        tree_kd_curve = None
        try:
            rf_spot = data.get("rf_spot")
            rd_spot = data.get("rd_spot")
            if rf_spot and rd_spot:
                tree_rf_curve = _spot_to_step_forwards(rf_spot, params.T, tree_steps)
                tree_kd_curve = _spot_to_step_forwards(rd_spot, params.T, tree_steps)
        except Exception:
            tree_rf_curve = None
            tree_kd_curve = None

        # TF tree
        try:
            tf_kw = {"bond_discrete": False}
            if tree_rf_curve and tree_kd_curve:
                tf_kw["rf_curve"] = tree_rf_curve
                tf_kw["kd_curve"] = tree_kd_curve
            tf_res = tf_rcps(params, steps=tree_steps, collect_tree=True, **tf_kw)
            tf_tree = tf_res.get("tree")
            tf_fv   = tf_res.get("fair_value")
        except Exception as e:
            tf_tree = {"error": str(e)}
            tf_fv   = None

        # GS tree
        try:
            gs_kw = {"bond_discrete": False}
            if data.get("gs_params"):
                gp = data["gs_params"]
                for k in ("enterprise_value", "net_debt", "common_shares", "rcps_shares"):
                    v = _f(gp.get(k))
                    if v:
                        gs_kw[k] = v
            if tree_rf_curve and tree_kd_curve:
                gs_kw["rf_curve"] = tree_rf_curve
                gs_kw["kd_curve"] = tree_kd_curve
            gs_res = gs_rcps(params, steps=tree_steps, collect_tree=True, **gs_kw)
            gs_tree = gs_res.get("tree")
            gs_fv   = gs_res.get("fair_value")
        except Exception as e:
            gs_tree = {"error": str(e)}
            gs_fv   = None

        return jsonify({
            "status": "ok",
            "steps":  tree_steps,
            "tf":     tf_tree,
            "gs":     gs_tree,
            "tf_fv":  tf_fv,
            "gs_fv":  gs_fv,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def download():
    try:
        data = request.json
        params = parse_params(data["params"])
        # ── 선도이자율 커브 (term structure, optional)
        dl_rf_curve = None
        dl_kd_curve = None
        try:
            rf_spot = data.get("rf_spot")
            rd_spot = data.get("rd_spot")
            if rf_spot and rd_spot:
                dl_rf_curve = _spot_to_step_forwards(rf_spot, params.T, max(int(round(params.T * 12)), 12))
                dl_kd_curve = _spot_to_step_forwards(rd_spot, params.T, max(int(round(params.T * 12)), 12))
        except Exception:
            dl_rf_curve = None
            dl_kd_curve = None
        dl_kw = {}
        if dl_rf_curve and dl_kd_curve:
            dl_kw["rf_curve"] = dl_rf_curve
            dl_kw["kd_curve"] = dl_kd_curve
        result = tf_rcps(params, **dl_kw)
        subsequent = []
        if data.get("reporting_dates"):
            from valuation.subsequent import subsequent_measurement
            rd = [{
                "date": date.fromisoformat(e["date"]),
                "stock_price": float(e["stock_price"]),
                "volatility": float(e["volatility"]),
                "risk_free_rate": float(e.get("risk_free_rate", params.risk_free_rate)),
                "credit_spread": float(e.get("credit_spread", params.credit_spread)),
            } for e in data["reporting_dates"]]
            subsequent = subsequent_measurement(params, rd, steps=60)
            # report.py 스키마에 맞게 키 매핑
            for row in subsequent:
                row["straight_bond_value"] = row.get("bond_value", 0)
                row["conversion_component"] = row.get("fair_value", 0) - row.get("bond_value", 0)

        sens = sensitivity_analysis(params, steps=60)

        # 이항 파라미터 (u/d/p) — 조서 모델정보용
        steps_r = result["steps"]
        dt = params.T / steps_r if steps_r else params.T
        u = float(np.exp(params.volatility * np.sqrt(dt)))
        d = 1.0 / u
        p_rn = float((np.exp((params.risk_free_rate - params.dividend_yield) * dt) - d) / (u - d))

        initial_adapted = {
            "fair_value": result["fair_value"],
            "straight_bond_value": result["bond_component"],
            "conversion_component": result["equity_component"],
            "model": result["model"],
            "steps": result["steps"],
            "binomial_detail": {
                "risk_neutral_prob": p_rn,
                "discount_rate": params.discount_rate,
                "u": u,
                "d": d,
            },
            "key_inputs": {
                "time_to_maturity": params.T,
                "stock_price": params.stock_price,
                "volatility": params.volatility,
                "risk_free_rate": params.risk_free_rate,
                "credit_spread": params.credit_spread,
            },
        }

        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.close()
        generate_workpaper(params, initial_adapted, subsequent, sens, tmp.name)
        return send_file(tmp.name, as_attachment=True,
                         download_name="RCPS_감사조서.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 400


# ── ECOS 국채/회사채 수익률 ──────────────────────────────────────────
ECOS_BASE = "https://ecos.bok.or.kr/api"

def _ecos_get(path, timeout=12):
    with urllib.request.urlopen(f"{ECOS_BASE}/{path}", timeout=timeout) as r:
        return json.loads(r.read())

# 817Y002 (시장금리 일별) 항목 — 코드는 ECOS debug로 확인된 값
_ECOS_ITEMS = [
    {"key": "KTB_1Y",    "code": "010190000", "name": "국고채(1년)",           "maturity": 1,  "category": "국고채"},
    {"key": "KTB_2Y",    "code": "010195000", "name": "국고채(2년)",           "maturity": 2,  "category": "국고채"},
    {"key": "KTB_3Y",    "code": "010200000", "name": "국고채(3년)",           "maturity": 3,  "category": "국고채"},
    {"key": "KTB_5Y",    "code": "010200001", "name": "국고채(5년)",           "maturity": 5,  "category": "국고채"},
    {"key": "KTB_10Y",   "code": "010210000", "name": "국고채(10년)",          "maturity": 10, "category": "국고채"},
    {"key": "KTB_20Y",   "code": "010220000", "name": "국고채(20년)",          "maturity": 20, "category": "국고채"},
    {"key": "KTB_30Y",   "code": "010230000", "name": "국고채(30년)",          "maturity": 30, "category": "국고채"},
    {"key": "CB_AA-",    "code": "010300000", "name": "회사채(3년, AA-)",      "maturity": 3,  "category": "회사채 AA-"},
    {"key": "CB_AA-_MP", "code": "010310000", "name": "회사채(3년, AA-, 민평)", "maturity": 3,  "category": "회사채 AA-(민평)"},
    {"key": "CB_BBB-",   "code": "010320000", "name": "회사채(3년, BBB-)",     "maturity": 3,  "category": "회사채 BBB-"},
    {"key": "MSB_1Y",    "code": "010400001", "name": "통안증권(1년)",          "maturity": 1,  "category": "통안증권"},
    {"key": "MSB_2Y",    "code": "010400002", "name": "통안증권(2년)",          "maturity": 2,  "category": "통안증권"},
]

@app.route("/api/rates/ecos/debug")
def ecos_debug():
    """ECOS 테이블/항목 원본 확인용 — 개발 전용"""
    api_key = request.args.get("key", "").strip()
    if not api_key:
        return jsonify({"error": "key 필요"}), 400
    try:
        # 채권 관련 테이블 목록
        td = _ecos_get(f"StatisticTableList/{api_key}/json/kr/1/500/")
        tables = td.get("StatisticTableList", {}).get("row", [])
        bond_tables = [t for t in tables if any(k in t.get("STAT_NAME","") for k in ["채권","금리","수익률"])]

        # 722Y001 항목 원본
        id1 = _ecos_get(f"StatisticItemList/{api_key}/json/kr/1/500/722Y001")
        items_722 = id1.get("StatisticItemList", {}).get("row", [])

        # 817Y002 항목 원본
        id2 = _ecos_get(f"StatisticItemList/{api_key}/json/kr/1/500/817Y002")
        items_817 = id2.get("StatisticItemList", {}).get("row", [])

        return jsonify({
            "bond_tables": bond_tables[:30],
            "items_722Y001_first30": [{"code": r.get("ITEM_CODE"), "name": r.get("ITEM_NAME")} for r in items_722[:30]],
            "items_817Y002_first30": [{"code": r.get("ITEM_CODE"), "name": r.get("ITEM_NAME")} for r in items_817[:30]],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/rates/ecos")
def get_ecos_rates():
    api_key = request.args.get("key", "").strip()
    target_date = request.args.get("date", "").strip()
    if not api_key:
        return jsonify({"status": "error", "message": "ECOS API 키가 필요합니다."}), 400
    try:
        # 최근 45일 범위에서 최신값 조회 (817Y002 = 시장금리 일별)
        if target_date:
            end_d = target_date
            start_d = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
        else:
            end_d = datetime.now().strftime("%Y%m%d")
            start_d = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")

        result = []
        for item in _ECOS_ITEMS:
            try:
                d2 = _ecos_get(
                    f"StatisticSearch/{api_key}/json/kr/1/45/817Y002/D/{start_d}/{end_d}/{item['code']}"
                )
                r2 = d2.get("StatisticSearch", {}).get("row", [])
                valid = [x for x in r2 if x.get("DATA_VALUE", "").strip() not in ("", "-")]
                if not valid:
                    continue
                latest = max(valid, key=lambda x: x["TIME"])
                result.append({
                    "key": item["key"],
                    "name": item["name"],
                    "maturity": item["maturity"],
                    "category": item["category"],
                    "yield": round(float(latest["DATA_VALUE"]) / 100, 6),
                    "yield_pct": round(float(latest["DATA_VALUE"]), 4),
                    "date": latest["TIME"],
                })
            except Exception:
                continue

        if not result:
            return jsonify({"status": "error", "message": "수익률 데이터를 가져오지 못했습니다. API 키 또는 조회 날짜를 확인하세요."}), 400

        return jsonify({"status": "ok", "rates": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# ── KIS-Net 민평표 파일 업로드 ────────────────────────────────────────
# 기본 만기 토큰: 3M, 6M, 1Y, 3Y, 3개월, 6개월, 1년, 1.5년 등
_MATURITY_RE = re.compile(
    r'^\s*(\d+(?:\.\d+)?)\s*([MyYmM]|개월|년)\s*$'
)
# 복합 토큰: 1Y6M 형식 (선택적)
_MATURITY_COMPOUND_RE = re.compile(
    r'^\s*(\d+)\s*[Yy년]\s*(\d+)\s*[Mm개월]\s*$'
)


def _parse_mat_token(tok):
    """만기 토큰 → 년 단위 float. 인식 불가이면 None."""
    if tok is None:
        return None
    s = str(tok).strip()
    # 복합형: 1Y6M
    mc = _MATURITY_COMPOUND_RE.match(s)
    if mc:
        return float(mc.group(1)) + float(mc.group(2)) / 12.0
    m = _MATURITY_RE.match(s)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2)
    if unit in ('M', 'm', '개월'):
        return val / 12.0
    return val  # Y / y / 년


def _cell_to_float(v):
    """셀 값 → float. 결측·비숫자이면 None."""
    if v is None:
        return None
    sv = str(v).strip().replace(',', '')  # 천단위 콤마 제거
    if sv in ('', '-', 'N/A', 'n/a', 'NA', '—', '–'):
        return None
    try:
        return float(sv)
    except (ValueError, TypeError):
        return None


def _run_row_header_logic(rows):
    """
    행-헤더 방향: 만기 토큰 >=4개인 헤더 행을 찾아
    [{"category","subtype","label","points"}] 반환.
    못 찾으면 빈 리스트.
    """
    if not rows:
        return []

    # 1. 헤더 행 탐색: 만기 토큰 >=4개인 첫 행
    header_idx = None
    mat_cols = {}  # col_index -> years
    for ri, row in enumerate(rows):
        hits = {}
        for ci, cell in enumerate(row):
            yr = _parse_mat_token(cell)
            if yr is not None:
                hits[ci] = yr
        if len(hits) >= 4:
            header_idx = ri
            mat_cols = hits
            break

    if header_idx is None or not mat_cols:
        return []

    first_mat_col = min(mat_cols)
    label_cols = list(range(first_mat_col))  # 0..N-1 레이블 열

    # 2. 레이블 열 forward-fill
    ff = [None] * max(len(label_cols), 1)
    data_rows = []
    for row in rows[header_idx + 1:]:
        padded = list(row) + [None] * max(0, first_mat_col - len(row))
        label_vals = []
        for li, ci in enumerate(label_cols):
            cell_val = padded[ci] if ci < len(padded) else None
            sv = str(cell_val).strip() if cell_val is not None else ''
            if sv and sv not in ('-',):
                ff[li] = sv
            label_vals.append(ff[li])
        data_rows.append((label_vals, row))

    # 3. 각 데이터 행에서 포인트 수집
    series = []
    for label_vals, row in data_rows:
        if not label_vals or label_vals[-1] is None:
            continue
        points = []
        for ci, yr in mat_cols.items():
            fv = _cell_to_float(row[ci] if ci < len(row) else None)
            if fv is not None:
                points.append({"t": yr, "y": fv})
        if not points:
            continue
        points.sort(key=lambda p: p["t"])
        category = label_vals[0] if len(label_vals) > 0 else None
        subtype  = label_vals[1] if len(label_vals) > 1 else None
        label    = label_vals[-1]
        series.append({
            "category": category,
            "subtype":  subtype,
            "label":    label,
            "points":   points,
        })
    return series


def _transpose_grid(rows):
    """그리드 전치: 짧은 행은 None으로 패딩 후 zip."""
    if not rows:
        return []
    max_cols = max(len(r) for r in rows)
    padded = [list(r) + [None] * (max_cols - len(r)) for r in rows]
    return [list(col) for col in zip(*padded)]


def _extract_series_from_grid(grid):
    """
    행-헤더 방향 시도 후 series < 1이면 전치 후 재시도.
    두 방향 모두 실패하면 빈 리스트.
    """
    rows = [list(r) for r in grid]
    series = _run_row_header_logic(rows)
    if len(series) < 1:
        series = _run_row_header_logic(_transpose_grid(rows))
    return series


def _merge_series(existing, new_series):
    """
    (label, subtype) 키로 중복 제거: 포인트 수가 더 많은 쪽 유지.
    """
    index = {}
    for s in existing:
        key = (s.get('label'), s.get('subtype'))
        if key not in index or len(s['points']) > len(index[key]['points']):
            index[key] = s
    for s in new_series:
        key = (s.get('label'), s.get('subtype'))
        if key not in index or len(s['points']) > len(index[key]['points']):
            index[key] = s
    return list(index.values())


def _parse_minpyung_grid(grid):
    """
    2D list(grid) → [{"category","subtype","label","points"}]
    grid는 openpyxl iter_rows(values_only=True) 또는 csv.reader 결과.
    하위 호환: _extract_series_from_grid 에 위임.
    """
    return _extract_series_from_grid(grid)


@app.route("/api/rates/upload", methods=["POST"])
def upload_minpyung():
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "파일이 없습니다."}), 400
        f = request.files['file']
        filename = (f.filename or '').lower()
        raw = f.read()

        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
            ws = wb.worksheets[0]
            grid = list(ws.iter_rows(values_only=True))
            series = _extract_series_from_grid(grid)

        elif filename.endswith('.csv'):
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('cp949', errors='replace')
            grid = list(csv.reader(io.StringIO(text)))
            series = _extract_series_from_grid(grid)

        elif filename.endswith('.pdf'):
            import pdfplumber  # lazy import — PDF 요청에만 비용 발생
            series = []
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages:
                    page_series = []
                    # 1차: extract_tables() → 각 테이블을 그리드로 처리
                    try:
                        tables = page.extract_tables() or []
                    except Exception:
                        tables = []
                    for tbl in tables:
                        if tbl:
                            found = _extract_series_from_grid(tbl)
                            page_series = _merge_series(page_series, found)
                    # 2차: 테이블에서 못 찾은 경우 텍스트 → 공백 분리 그리드
                    if not page_series:
                        try:
                            txt = page.extract_text() or ''
                        except Exception:
                            txt = ''
                        if txt.strip():
                            text_grid = [
                                re.split(r'\s{2,}', line)
                                for line in txt.splitlines()
                                if line.strip()
                            ]
                            page_series = _extract_series_from_grid(text_grid)
                    series = _merge_series(series, page_series)

        else:
            return jsonify({
                "status": "error",
                "message": "xlsx, xls, csv, pdf 파일만 지원합니다.",
            }), 400

        if not series:
            return jsonify({
                "status": "error",
                "message": "표 형식을 인식하지 못했습니다. 헤더에 3M/1Y/3Y 등 만기 열이 있는지 확인하세요.",
            }), 400

        return jsonify({"status": "ok", "series": series})
    except Exception:
        return jsonify({
            "status": "error",
            "message": "파일 처리 중 오류가 발생했습니다. 파일 형식 및 만기 헤더(3M/1Y/3Y 등)를 확인하세요.",
        }), 400


def _extract_contract_text(filename, raw):
    """계약서 파일에서 전체 텍스트 추출 (PDF: pdfplumber, xlsx: openpyxl)."""
    fn = (filename or '').lower()
    if fn.endswith('.pdf'):
        import pdfplumber
        parts = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ''
                except Exception:
                    t = ''
                if t.strip():
                    parts.append(t)
        return "\n".join(parts)
    if fn.endswith('.xlsx') or fn.endswith('.xls'):
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        parts = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c not in (None, "")]
                if cells:
                    parts.append("\t".join(cells))
        return "\n".join(parts)
    if fn.endswith('.csv') or fn.endswith('.txt'):
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('cp949', errors='replace')
    raise ValueError("지원하지 않는 파일 형식")


_CONTRACT_PROMPT = """당신은 한국 상환전환우선주(RCPS) 신주인수계약서를 분석하는 회계·법무 전문가입니다.
아래 계약서 전문을 읽고, 다음 JSON 스키마에 맞춰 **오직 JSON만** 출력하세요(코드블록·설명 금지).
모든 금액은 숫자(콤마 없이), 날짜는 YYYY-MM-DD.

{
  "section1_발행조건": {
    "종류": "", "우선주의_종류": "", "우선주_의결권": "",
    "발행일": "", "주식수": 0, "주당발행금액": 0, "총발행금액": 0, "액면가액": 0,
    "존속기간": "", "전환비율": "", "전환가액조정": [],
    "전환청구기간": "", "상환청구기간": "", "상환가액": "", "우선배당률": ""
  },
  "valuation_inputs": {
    "issue_date": "", "maturity_date": "", "face_value": 0, "rcps_shares": 0,
    "conversion_price": 0, "coupon_rate": 0.0, "put_irr": 0.0,
    "conversion_start": "", "conversion_ratio": 1.0
  },
  "analysis_sections": [
    {
      "title": "섹션 제목",
      "type": "table | list | text",
      "columns": ["표일 때 열 제목들"],
      "rows": [["표일 때 행 데이터"]],
      "items": ["목록일 때 항목들"],
      "body": "서술형일 때 본문",
      "note": "보조 설명(선택)"
    }
  ],
  "담보제공자산": ""
}

규칙:
- section1_발행조건 과 valuation_inputs 는 **모든 RCPS 공통 항목**이므로 위 고정 스키마대로 정확히 추출하세요.
  valuation_inputs: coupon_rate/put_irr 는 소수(예 7.5%→0.075), issue_date 는 발행일(거래종결일 다음날이면 그 날짜),
  conversion_start 는 전환청구 시작일(발행일+6개월 등).
- **analysis_sections 는 당신이 자율적으로 구성**하세요. RCPS마다 상장 전/후 구조·상환/풋옵션 조건·사전동의·약정·담보 등이
  모두 다르므로, 고정된 틀을 따르지 말고 **이 계약서에 실제로 존재하는 내용**만 골라 가장 적합한 섹션 구분과 표현
  (표/목록/서술)을 직접 결정하세요. 섹션 개수·제목·형식은 계약 내용에 맞춰 자유롭게 정하면 됩니다.
  예시 주제(있는 것만): 상장 전/후 권리구조, 상환사유·방법, 전환가액 조정(리픽싱), 풋/콜옵션 종류별 조건(IRR 등),
  사전동의·통지 사항, 진술·보장, 손해배상, 기한이익상실, 양도제한, 특이조항 등.
- type 이 "table"이면 columns/rows 만, "list"면 items 만, "text"면 body 만 채우고 나머지는 생략 가능.
- 분석 의견은 계약 조항에 근거해 작성하고, 외부정보(지분율·MOU 비교 등)가 필요하면 "계약서 외 정보 필요"로 표기하세요.

=== 계약서 전문 ===
"""


@app.route("/api/contract/parse", methods=["POST"])
def contract_parse():
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "파일이 없습니다."}), 200
        f = request.files['file']
        raw = f.read()
        api_key = (request.form.get('api_key') or os.environ.get('ANTHROPIC_API_KEY') or '').strip()
        model = request.form.get('model') or 'claude-sonnet-4-6'
        if not api_key:
            return jsonify({"status": "error",
                            "message": "Anthropic API 키가 필요합니다. 키를 입력하세요."}), 200

        try:
            text = _extract_contract_text(f.filename, raw)
        except Exception:
            return jsonify({"status": "error",
                            "message": "파일에서 텍스트를 추출하지 못했습니다. PDF/Excel 형식을 확인하세요."}), 200
        if not text or not text.strip():
            return jsonify({"status": "error",
                            "message": "계약서 텍스트가 비어 있습니다(스캔 이미지 PDF일 수 있음)."}), 200
        text = text[:200000]

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=model,
                max_tokens=8000,
                messages=[{"role": "user", "content": _CONTRACT_PROMPT + text}],
            )
            out = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        except Exception as e:
            return jsonify({"status": "error",
                            "message": f"LLM 호출 오류: {str(e)[:200]}"}), 200

        # JSON 추출 (코드블록/잡텍스트 방어)
        m = re.search(r'\{.*\}', out, re.DOTALL)
        if not m:
            return jsonify({"status": "error",
                            "message": "요약 JSON을 파싱하지 못했습니다."}), 200
        try:
            summary = json.loads(m.group(0))
        except Exception:
            return jsonify({"status": "error",
                            "message": "요약 JSON 형식 오류."}), 200

        return jsonify({"status": "ok", "summary": summary})
    except Exception:
        return jsonify({"status": "error",
                        "message": "계약서 처리 중 오류가 발생했습니다."}), 200


if __name__ == "__main__":
    print("RCPS 평가툴 서버 시작: http://localhost:5000")
    app.run(debug=True, port=5000, host="0.0.0.0")
