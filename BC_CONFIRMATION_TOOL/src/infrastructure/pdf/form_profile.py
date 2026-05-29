from pathlib import Path
import yaml

_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "form_profiles.yaml"


class FormProfile:
    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load(cls, path: Path | None = None) -> "FormProfile":
        p = path or _CONFIG
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        norm = {fam: {int(k): v for k, v in secs.items()} for fam, secs in raw.items()}
        return cls(norm)

    def route(self, family: str, section_no: int) -> dict | None:
        """(family, 섹션번호) → {ac, direction?, sub?} 또는 None."""
        return self._data.get(family, {}).get(section_no)
