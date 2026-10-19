"""Development-only external reference metadata and historical format compatibility."""
import json
from pathlib import Path

_DATA = json.loads(Path(__file__).with_name("research-reference.json").read_text(encoding="utf-8"))["texts"]


def research_text(key: str) -> str:
    """Return an exact configured value; unknown keys are errors."""
    value = _DATA[key]
    if not isinstance(value, str):
        raise TypeError("Research metadata values must be strings")
    return value
