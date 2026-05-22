import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, send_file, send_from_directory
from datetime import date, datetime, timedelta
import tempfile, traceback, json
import urllib.request, urllib.error
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
        dividend_cumulative=bool(data.get("dividend_cumulative", True)),
        dividend_first_pay_year=float(data.get("dividend_first_pay_year", 0) or 0),
        conversion_price=float(data.get("conversion_price", 0)),
        conversion_start=_d(data.get("conversion_start")),
        put_start=_d(data.get("put_start")),
        put_irr=float(data.get("put_irr", 0)),
        put_price_mode=data.get("put_price_mode", "irr"),
        put_fixed_price=float(data.get("put_fixed_price", 0) or 0),
        put_coupon_netting=data.get("put_coupon_netting", "accrual"),
        put_contract_ratio=float(data.get("put_contract_ratio", 0) or 0),
        call_start=_d(data.get("call_start")),
        call_irr=float(data.get("call_irr", 0)),
        call_price_mode=data.get("call_price_mode", "irr"),
        call_fixed_price=float(data.get("call_fixed_price", 0) or 0),
        call_contract_ratio=float(data.get("call_contract_ratio", 0) or 0),
        call_coupon_netting=data.get("call_coupon_netting", "accrual"),
        refixing=bool(data.get("refixing", False)),
        refixing_floor=_f(data.get("refixing_floor")),
        refixing_trigger=_f(data.get("refixing_trigger")),
        refixing_frequency=data.get("refixing_frequency", "continuous"),
        refixing_ratchet=bool(data.get("refixing_ratchet", True)),
        refixing_vwap_window=int(data.get("refixing_vwap_window", 0) or 0),
        call_soft_barrier=_f(data.get("call_soft_barrier")),
        call_soft_window=int(data.get("call_soft_window", 1) or 1),
        call_soft_count=int(data.get("call_soft_count", 1) or 1),
        mandatory_conv_barrier=_f(data.get("mandatory_conv_barrier")),
        mandatory_conv_window=int(data.get("mandatory_conv_window", 1) or 1),
        mandatory_conv_count=int(data.get("mandatory_conv_count", 1) or 1),
        put_barrier=_f(data.get("put_barrier")),
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
            # 경로의존(래칫 리픽싱 등) 활성 시 트리(TF/GS)는 과소반영 → MC 전용 평가로 라우팅
            "mc_only": bool(params.requires_mc),
            "mc_only_reason": params.mc_only_reason,
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
    "conversion_start": "", "conversion_ratio": 1.0,
    "refixing": false, "refixing_floor": 0.0, "refixing_trigger": 1.0, "refixing_frequency": "continuous"
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
  valuation_inputs 매핑(혼동 주의):
    · face_value = 총발행금액(= 주식수 × 주당발행금액), rcps_shares = 우선주 주식수, conversion_price = 전환가액(원/주)
    · coupon_rate = **우선배당률**(소수, 예 2%→0.02)
    · put_irr = **상환/풋옵션 보장수익률(IRR)**(소수, 예 7.5%→0.075)
    · ★ coupon_rate(우선배당률)와 put_irr(보장수익률)은 서로 다른 항목이니 **절대 바꿔 넣지 마세요**.
    · issue_date = 발행일(거래종결일 다음날이면 그 날짜), maturity_date = 만기일, conversion_start = 전환청구 시작일(발행일+6개월 등).
    · refixing = 전환가액 조정(리픽싱) 조항이 있으면 true (저가발행·IPO 하향조정·시가연동 등)
    · refixing_floor = 전환가 조정 하한을 **최초 전환가액 대비 비율**(0~1)로. 하한이 액면가면 액면가÷전환가액, "최초 전환가의 70%"면 0.70
    · refixing_trigger = 주가/발행가가 전환가의 이 비율 미만일 때 조정(0~1). 명시 트리거 없으면 0.90
    · refixing_frequency = 조정 주기 ("continuous"|"quarterly"|"semi-annual"|"annual"). 명시 없으면 "continuous"
- **analysis_sections 는 당신이 자율적으로 구성**하세요. RCPS마다 상장 전/후 구조·상환/풋옵션 조건·사전동의·약정·담보 등이
  모두 다르므로, 고정된 틀을 따르지 말고 **이 계약서에 실제로 존재하는 내용**만 골라 가장 적합한 섹션 구분과 표현
  (표/목록/서술)을 직접 결정하세요. 섹션 개수·제목·형식은 계약 내용에 맞춰 자유롭게 정하면 됩니다.
  예시 주제(있는 것만): 상장 전/후 권리구조, 상환사유·방법, 전환가액 조정(리픽싱), 풋/콜옵션 종류별 조건(IRR 등),
  사전동의·통지 사항, 진술·보장, 손해배상, 기한이익상실, 양도제한, 특이조항 등.
- type 이 "table"이면 columns/rows 만, "list"면 items 만, "text"면 body 만 채우고 나머지는 생략 가능.
- 분석 의견은 계약 조항에 근거해 작성하고, 외부정보(지분율·MOU 비교 등)가 필요하면 "계약서 외 정보 필요"로 표기하세요.

=== 계약서 전문 ===
"""


# 로컬 소형모델(Ollama)용 — 더 직접적·강제적이고 분석 섹션을 고정·단순화
_CONTRACT_PROMPT_LOCAL = """당신은 한국 상환전환우선주(RCPS) 계약서를 분석하는 회계 전문가입니다.
아래 계약서에서 정보를 추출해 **오직 JSON만** 출력하세요. 설명·코드블록 금지.
금액은 콤마 없는 숫자, 비율은 소수(예 7.5%→0.075), 날짜는 YYYY-MM-DD.
**각 항목을 계약서에서 반드시 찾아 채우세요. 숫자 항목을 빈칸/0 으로 방치하지 말고 본문에서 값을 찾으세요.**

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
    "conversion_start": "", "conversion_ratio": 1.0,
    "refixing": false, "refixing_floor": 0.0, "refixing_trigger": 1.0, "refixing_frequency": "continuous"
  },
  "analysis_sections": [
    {"title": "전환·리픽싱 조건", "type": "list", "items": []},
    {"title": "상환·풋옵션·콜옵션 조건", "type": "list", "items": []},
    {"title": "주요 약정·특이사항", "type": "list", "items": []}
  ],
  "담보제공자산": ""
}

추출 지침(중요):
- 총발행금액 = 주식수 × 주당발행금액. face_value = 총발행금액.
- conversion_price = 전환가액(원/주). coupon_rate = 우선배당률(소수). put_irr = 상환/풋 보장수익률 IRR(소수).
- issue_date=발행일, maturity_date=만기일(존속기간 종료일), conversion_start=전환청구 시작일.
- refixing=전환가액 조정(리픽싱) 조항 있으면 true. refixing_floor=조정 하한÷전환가액(액면가 하한이면 액면가÷전환가액). refixing_trigger=명시 없으면 0.90. refixing_frequency=명시 없으면 "continuous".
- analysis_sections 의 items 는 위 3개 섹션 제목 그대로 두고, 계약서에 있는 해당 내용을 짧은 한국어 문장으로 채우세요.
- 위 JSON 키/구조를 그대로 사용하고, 추가 키는 만들지 마세요.

=== 계약서 전문 ===
"""


def _ocr_pdf(raw: bytes, lang: str = "kor+eng", max_pages: int = 50, dpi: int = 300) -> str:
    """스캔 PDF 로컬 OCR: PyMuPDF로 페이지 렌더 → Tesseract로 텍스트 인식.
    Tesseract 바이너리 필요(미설치 시 예외 → 호출부에서 비전 폴백)."""
    import fitz, pytesseract
    from PIL import Image
    tcmd = os.environ.get("TESSERACT_CMD")
    if not tcmd:
        cand = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(cand):
            tcmd = cand
    if tcmd:
        pytesseract.pytesseract.tesseract_cmd = tcmd
    doc = fitz.open(stream=raw, filetype="pdf")
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    parts = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # --psm 6(uniform block): 한국어 인식에 기본 psm 3 보다 안정적
            try:
                txt = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
            except pytesseract.TesseractError:
                txt = pytesseract.image_to_string(img, lang="eng", config="--psm 6")  # 한국어 데이터 없으면 영어
            if txt.strip():
                parts.append(txt)
    finally:
        doc.close()
    return "\n".join(parts)


def _parse_gemini_429(detail: str):
    """Gemini 429 응답에서 (quotaId, retryDelay초) 추출."""
    qid, delay = '', 0
    try:
        ej = json.loads(detail)
        for d in ej.get('error', {}).get('details', []):
            t = d.get('@type', '')
            if t.endswith('QuotaFailure'):
                for v in d.get('violations', []):
                    qid = v.get('quotaId') or v.get('quotaMetric') or qid
            if t.endswith('RetryInfo'):
                m = re.match(r'(\d+)', str(d.get('retryDelay', '')))
                if m:
                    delay = int(m.group(1))
    except Exception:
        pass
    return qid, delay


def _llm_summarize(provider: str, api_key: str, model: str, prompt: str,
                   pdf_bytes: bytes = None) -> str:
    """계약서 요약 LLM 호출 — provider: 'gemini'(무료티어) | 'anthropic'.
    pdf_bytes 가 주어지면 비전(멀티모달)으로 PDF 를 직접 첨부 → 스캔본도 모델이 OCR/이해.
    Gemini 는 추가 의존성 없이 REST(urllib) 로 호출."""
    import base64
    if provider == "gemini":
        m = model if model.startswith("gemini") else "gemini-2.0-flash"
        parts = [{"text": prompt}]
        if pdf_bytes:
            parts.append({"inline_data": {
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode("ascii")}})
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{m}:generateContent?key={api_key}")
        body = json.dumps({
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
        }).encode("utf-8")
        import time
        resp = None
        for attempt in range(2):
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    resp = json.loads(r.read())
                break
            except urllib.error.HTTPError as he:
                detail = he.read().decode("utf-8", "ignore")
                if he.code == 429:
                    qid, delay = _parse_gemini_429(detail)
                    # 분당 한도(짧은 retryDelay): 자동 1회 대기 후 재시도
                    if attempt == 0 and 0 < delay <= 30:
                        time.sleep(delay + 1)
                        continue
                    kind = ("분당 한도(잠시 후 자동 해소)" if delay and delay <= 60
                            else "일일 한도 소진 추정 → PT 자정(한국 오후 5시경) 리셋 또는 다른 키/모델")
                    raise RuntimeError(
                        f"무료 한도 초과(429). 한도종류={qid or '미상'}, 권장대기={delay or '?'}초. {kind}.")
                raise RuntimeError(f"Gemini API {he.code}: {detail[:250]}")
        cands = resp.get("candidates") or []
        if not cands:
            raise RuntimeError(f"Gemini 응답 비어있음: {str(resp.get('promptFeedback'))[:200]}")
        parts_out = (cands[0].get("content", {}) or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts_out).strip()

    if provider == "groq":
        # Groq (무료·빠름, OpenAI 호환) — 텍스트 전용(비전 미지원)
        m = model if model else "llama-3.3-70b-versatile"
        body = json.dumps({
            "model": m,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2, "max_tokens": 8000,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}",
                     "User-Agent": "Mozilla/5.0 (compatible; RCPS-Tool/1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as he:
            detail = he.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"Groq API {he.code}: {detail}")
        return ((resp.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "").strip()

    if provider == "ollama":
        # 로컬 Ollama (무료·무제한·기밀) — 텍스트 전용. api_key 불필요.
        host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        m = model or "qwen2.5:7b"
        # 입력 길이에 맞춰 컨텍스트 설정(과도한 RAM 방지 위해 상한). 초과분은 잘림.
        approx_tokens = len(prompt) // 3 + 1200
        num_ctx = max(8192, min(((approx_tokens // 2048) + 1) * 2048, 32768))
        body = json.dumps({
            "model": m,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",   # 유효 JSON 강제 (로컬 소형모델 JSON 안정화)
            "options": {"temperature": 0.2, "num_ctx": num_ctx},
        }).encode("utf-8")
        req = urllib.request.Request(host + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:  # CPU 추론 느림 → 최대 15분
                resp = json.loads(r.read())
        except urllib.error.HTTPError as he:
            detail = he.read().decode("utf-8", "ignore")[:250]
            raise RuntimeError(f"Ollama {he.code}: {detail} (모델 설치 확인: ollama pull {m})")
        except urllib.error.URLError as ue:
            raise RuntimeError(f"Ollama 연결 실패: {ue.reason}. 'ollama' 실행 여부와 모델 설치를 확인하세요.")
        return ((resp.get("message") or {}).get("content") or "").strip()

    if provider == "claude_cli":
        # 로컬에 설치된 Claude Code CLI 호출(사용자 Max 구독). 텍스트 전용.
        # 프롬프트는 stdin 으로 전달(대용량 대응), --output-format json 엔벨로프에서 result 추출.
        import subprocess, shutil, tempfile
        cmd = os.environ.get("CLAUDE_CLI_CMD") or shutil.which("claude") or "claude"
        # --allowed-tools "" : 도구 차단(파일읽기 등 에이전트 동작 방지)
        # cwd=중립 임시폴더 : 프로젝트 CLAUDE.md/메모리 자동로드로 인한 컨텍스트 오염 방지
        args = [cmd, "-p", "--output-format", "json",
                "--allowed-tools", "", "--no-session-persistence"]
        if model:
            args += ["--model", model]  # sonnet | opus | haiku
        try:
            proc = subprocess.run(args, input=prompt, capture_output=True,
                                  text=True, encoding="utf-8", timeout=600,
                                  cwd=tempfile.gettempdir())
        except FileNotFoundError:
            raise RuntimeError("claude CLI를 찾을 수 없습니다. 독립형 Claude Code 설치+로그인 후 PATH 등록 "
                               "(또는 환경변수 CLAUDE_CLI_CMD 에 실행파일 경로 지정).")
        except subprocess.TimeoutExpired:
            raise RuntimeError("claude CLI 응답 시간 초과(10분).")
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI 오류: {((proc.stderr or proc.stdout) or '')[:250]}")
        out = (proc.stdout or "").strip()
        try:                       # --output-format json → {"result": "...", ...}
            env = json.loads(out)
            if isinstance(env, dict) and env.get("result") is not None:
                return str(env["result"]).strip()
        except Exception:
            pass
        return out

    # anthropic (유료)
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    m = model if model.startswith("claude") else "claude-sonnet-4-6"
    if pdf_bytes:
        content = [
            {"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode("ascii")}},
            {"type": "text", "text": prompt},
        ]
    else:
        content = prompt
    msg = client.messages.create(
        model=m, max_tokens=8000,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


@app.route("/api/contract/parse", methods=["POST"])
def contract_parse():
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "파일이 없습니다."}), 200
        f = request.files['file']
        raw = f.read()
        api_key = (request.form.get('api_key') or '').strip()
        provider = (request.form.get('provider') or '').strip().lower()
        model = (request.form.get('model') or '').strip()
        if not provider:
            if api_key.startswith('sk-ant'):
                provider = 'anthropic'
            elif api_key.startswith('gsk_'):
                provider = 'groq'
            else:
                provider = 'gemini'
        if provider in ('ollama', 'claude_cli'):
            api_key = api_key or 'local'  # 로컬 Ollama / Claude CLI(구독)는 키 불필요
        if not api_key:
            _env = {'gemini': ('GEMINI_API_KEY', 'GOOGLE_API_KEY'),
                    'groq': ('GROQ_API_KEY',),
                    'anthropic': ('ANTHROPIC_API_KEY',)}.get(provider, ())
            for k in _env:
                if os.environ.get(k):
                    api_key = os.environ[k].strip(); break
        if not api_key:
            nm = {'gemini': 'Gemini', 'groq': 'Groq', 'anthropic': 'Anthropic'}.get(provider, provider)
            return jsonify({"status": "error",
                            "message": f"{nm} API 키가 필요합니다. 키를 입력하세요."}), 200

        fn = (f.filename or '').lower()
        is_pdf = fn.endswith('.pdf')
        try:
            text = _extract_contract_text(f.filename, raw)
        except Exception:
            text = ''
        # 텍스트가 거의 없으면(스캔 이미지 PDF) → 비전으로 PDF 직접 전달(모델이 OCR)
        scanned = is_pdf and len((text or '').strip()) < 100
        # Ollama(로컬)는 num_ctx 상한이 있어 지시문이 잘리지 않게 본문을 더 짧게 cap
        maxchars = 85000 if provider == 'ollama' else 200000
        # 로컬 소형모델은 강제·단순 프롬프트, 클라우드는 자율 분석 프롬프트
        cprompt = _CONTRACT_PROMPT_LOCAL if provider == 'ollama' else _CONTRACT_PROMPT
        try:
            if scanned:
                # 1순위: 로컬 OCR(Tesseract) → 가벼운 텍스트만 클라우드 전송(429 회피)
                ocr_text = ''
                try:
                    ocr_text = _ocr_pdf(raw)
                except Exception:
                    ocr_text = ''
                if ocr_text and len(ocr_text.strip()) >= 100:
                    out = _llm_summarize(provider, api_key, model,
                                         cprompt + ocr_text[:maxchars])
                elif provider in ('gemini', 'anthropic'):
                    # 2순위(비전 지원 모델만): 로컬 OCR 불가/실패 → PDF 직접 전달
                    if len(raw) > 18_000_000:
                        return jsonify({"status": "error",
                                        "message": "스캔 PDF가 큽니다(18MB 초과). 로컬 OCR(Tesseract) 설치 또는 페이지 분할 후 재시도하세요."}), 200
                    out = _llm_summarize(provider, api_key, model,
                                         _CONTRACT_PROMPT + "(첨부된 PDF 계약서를 직접 읽고 분석하세요. 스캔본이면 OCR하여 텍스트를 인식하세요.)",
                                         pdf_bytes=raw)
                else:
                    # Groq 등 텍스트 전용: 로컬 OCR 실패 시 비전 불가
                    return jsonify({"status": "error",
                                    "message": "스캔 PDF인데 로컬 OCR 추출에 실패했습니다. Tesseract 설치를 확인하거나, 비전 지원 제공자(Gemini/Claude)를 사용하세요."}), 200
            else:
                if not text or not text.strip():
                    return jsonify({"status": "error",
                                    "message": "계약서 텍스트가 비어 있습니다. PDF/Excel 형식을 확인하세요."}), 200
                out = _llm_summarize(provider, api_key, model, cprompt + text[:maxchars])
        except Exception as e:
            return jsonify({"status": "error",
                            "message": f"LLM 호출 오류: {str(e)[:250]}"}), 200

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


@app.route("/api/contract/loadfile", methods=["GET"])
def contract_loadfile():
    """Claude Code(사용자 Max 구독)가 생성한 요약 JSON 파일을 읽어 반환.
    경로: <project>/contract_summary.json — API 키·비용 없이 내 Claude로 요약 → 툴 연동."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contract_summary.json")
    if not os.path.exists(path):
        return jsonify({"status": "error",
                        "message": "contract_summary.json 이 없습니다. Claude Code에 '계약서 요약해서 contract_summary.json 으로 저장해줘'라고 요청하세요."}), 200
    try:
        with open(path, encoding="utf-8") as fp:
            summary = json.load(fp)
    except Exception as e:
        return jsonify({"status": "error",
                        "message": f"JSON 파싱 오류: {str(e)[:150]}"}), 200
    return jsonify({"status": "ok", "summary": summary})


if __name__ == "__main__":
    print("RCPS 평가툴 서버 시작: http://localhost:5000")
    app.run(debug=True, port=5000, host="0.0.0.0")
