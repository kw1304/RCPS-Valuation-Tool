"""RCPS 평가툴 서버 자동 실행 런처 (백그라운드용).
- debug/reloader 끔 (백그라운드에서 안정적)
- 127.0.0.1:5000 에서 서비스
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
