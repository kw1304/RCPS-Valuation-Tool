"""WAT 통합 서버
- 정적 파일 서빙 (WAT/, irs/ 등)
- /api/rates: ECOS BOK 직접 호출 (ECOS_API_KEY 환경변수 있으면 로컬, 없으면 Render fallback)
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import accounting

ROOT = Path(__file__).parent
PORT = int(os.environ.get("WAT_PORT", "8765"))
ACCOUNTING_DB = str(ROOT / "data" / "accounting.db")
ECOS_KEY = os.environ.get("ECOS_API_KEY", "").strip()
ECOS_BASE = "https://ecos.bok.or.kr/api"
RENDER_FALLBACK = "https://irs-tool.onrender.com/api/rates"

# IRS 호출하는 1Y~30Y 만기 매핑 (RCPS 코드 동일 — ECOS 817Y002 시장금리 일별)
_ECOS_ITEMS = [
    ("1Y", "010190000", 1),
    ("2Y", "010195000", 2),
    ("3Y", "010200000", 3),
    ("5Y", "010200001", 5),
    ("10Y", "010210000", 10),
    ("20Y", "010220000", 20),
    ("30Y", "010230000", 30),
]

app = Flask(__name__, static_folder=None)

(ROOT / "data").mkdir(exist_ok=True)
accounting.init_db(ACCOUNTING_DB)

_ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("WAT_ALLOWED_ORIGINS", "").split(",") if o.strip()}


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    # /api/* 만 CORS 허용 — 화이트리스트 origin 또는 *(키 없으면 default *)
    if request.path.startswith("/api/"):
        origin = request.headers.get("Origin", "")
        # 화이트리스트에 있는 origin만 허용. 미설정(_ALLOWED_ORIGINS 비어있음) 시 헤더 미부착 = 차단
        if _ALLOWED_ORIGINS and origin in _ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
    return resp


def _ecos_get(path, timeout=12):
    with urllib.request.urlopen(f"{ECOS_BASE}/{path}", timeout=timeout) as r:
        return json.loads(r.read())


def _fetch_ecos_rates(date_str):
    """date_str: YYYYMMDD. 반환: {"1Y":{"mid":x,"bid":None,"ask":None}, ...}"""
    if not ECOS_KEY:
        raise RuntimeError("ECOS_API_KEY 미설정")
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
    except Exception:
        d = datetime.now()
    end_d = d.strftime("%Y%m%d")
    start_d = (d - timedelta(days=45)).strftime("%Y%m%d")

    out = {}
    for key, code, _ in _ECOS_ITEMS:
        try:
            r = _ecos_get(
                f"StatisticSearch/{ECOS_KEY}/json/kr/1/45/817Y002/D/{start_d}/{end_d}/{code}"
            )
            rows = r.get("StatisticSearch", {}).get("row", [])
            valid = [x for x in rows if x.get("DATA_VALUE", "").strip() not in ("", "-")]
            if not valid:
                continue
            latest = max(valid, key=lambda x: x["TIME"])
            out[key] = {"mid": float(latest["DATA_VALUE"]), "bid": None, "ask": None}
        except Exception:
            continue
    return out


def _fetch_render_fallback(date_str):
    url = f"{RENDER_FALLBACK}?date={date_str}"
    with urllib.request.urlopen(url, timeout=12) as r:
        return json.loads(r.read())


_DATE_RE = __import__("re").compile(r"^\d{8}$")


@app.route("/api/rates")
def api_rates():
    date_str = request.args.get("date", "").strip() or datetime.now().strftime("%Y%m%d")
    if not _DATE_RE.match(date_str):
        return jsonify({"success": False, "error": "invalid date"}), 400

    if ECOS_KEY:
        try:
            rates = _fetch_ecos_rates(date_str)
            if rates:
                return jsonify({"success": True, "date": date_str, "rates": rates, "source": "ECOS-local"})
        except Exception as e:
            print(f"[api/rates] local ECOS 실패 → Render fallback: {e}", flush=True)

    # fallback
    try:
        data = _fetch_render_fallback(date_str)
        if "source" not in data:
            data["source"] = "Render-fallback"
        return jsonify(data)
    except Exception as e:
        print(f"[api/rates] Render fallback 실패: {e}", flush=True)
        return jsonify({"success": False, "error": "upstream unavailable"}), 502


@app.route("/api/accounting/ask", methods=["POST"])
def api_accounting_ask():
    body = request.get_json(silent=True) or {}
    conv_id = body.get("conversationId")
    question = body.get("question")
    framework = body.get("framework", "auto")
    mode = body.get("mode", "fast")
    if not conv_id or not question:
        return jsonify({"error": "conversationId와 question 필수"}), 400

    def generate():
        for ev in accounting.ask_stream(ACCOUNTING_DB, conv_id, question, framework, mode):
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return app.response_class(generate(), mimetype="text/event-stream")


@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "ecos_local": bool(ECOS_KEY),
        "source": "ECOS-local" if ECOS_KEY else "Render-fallback",
        "claude_cli": "present" if accounting.resolve_claude() else "absent",
    })


@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def static_files(path):
    # 디렉토리 진입 시 index.html 자동 매핑
    target = ROOT / path
    if target.is_dir():
        path = f"{path.rstrip('/')}/index.html"
    return send_from_directory(ROOT, path)


if __name__ == "__main__":
    print(f"WAT 서버: http://0.0.0.0:{PORT}  (ECOS local={'ON' if ECOS_KEY else 'OFF (Render fallback)'})")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
