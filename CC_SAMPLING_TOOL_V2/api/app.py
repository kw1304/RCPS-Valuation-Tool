"""Flask app factory with route registration."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, g
from src.infrastructure.db.session import make_engine, make_session


def _load_dotenv() -> None:
    """프로젝트 루트 .env 로드 (무의존). 이미 설정된 환경변수는 덮어쓰지 않음.

    KEY=VALUE 한 줄씩. # 주석·빈 줄 무시. 따옴표 제거.
    DART_API_KEY·ANTHROPIC_API_KEY·CC_MAPPING_PROVIDER 등 여기서 주입.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def create_app(testing: bool = False, session_factory=None) -> Flask:
    _load_dotenv()
    app = Flask(__name__, static_folder="../frontend",
                static_url_path="")
    app.config["TESTING"] = testing

    if session_factory is None:
        # Phase 1 fallback: default sqlite path. Ensure parent dir exists.
        from pathlib import Path
        Path("data").mkdir(parents=True, exist_ok=True)
        engine = make_engine()
        from src.infrastructure.db.models import Base
        Base.metadata.create_all(engine)
        session_factory = make_session(engine)
    app.config["SESSION_FACTORY"] = session_factory

    @app.before_request
    def open_session():
        g.session = session_factory()

    @app.teardown_request
    def close_session(exc):
        s = g.pop("session", None)
        if s is not None:
            # 예외 종료 시 미커밋 변경 폐기 — rollback 없이 close만 하면
            # 동일 요청 내 부분 write가 다음 세션에 새어나갈 수 있음.
            if exc is not None:
                s.rollback()
            s.close()

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/")
    def index():
        # 루트 접속 시 프론트(index.html) 서빙 — static_url_path=""라
        # /index.html은 자동 서빙되나 "/"는 라우트가 없어 404였음.
        return app.send_static_file("index.html")

    from api.routes.project import bp as project_bp
    app.register_blueprint(project_bp)

    from api.routes.ingest import bp as ingest_bp
    app.register_blueprint(ingest_bp)

    from api.routes.sampling import bp as sampling_bp
    app.register_blueprint(sampling_bp)

    from api.routes.state import bp as state_bp
    app.register_blueprint(state_bp)

    from api.routes.confirmations import bp as confirmations_bp
    app.register_blueprint(confirmations_bp)

    from api.routes.alternative import bp as alternative_bp
    app.register_blueprint(alternative_bp)

    from api.routes.projection import bp as projection_bp
    app.register_blueprint(projection_bp)

    from api.routes.workpaper import bp as workpaper_bp
    app.register_blueprint(workpaper_bp)

    from api.routes.upload_guide import bp as upload_guide_bp
    app.register_blueprint(upload_guide_bp)

    return app
