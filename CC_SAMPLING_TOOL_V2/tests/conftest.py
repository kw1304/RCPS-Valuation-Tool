"""tests 루트 conftest — src/ api/ 패키지 import 보장."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
