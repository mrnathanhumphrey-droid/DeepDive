"""
prompts/loader.py
Loads prompt text files from the prompts/ directory.
Files are cached after first read — zero repeated disk I/O per process.
"""

from pathlib import Path
from functools import lru_cache

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """Load a prompt by its path relative to prompts/, e.g. 'shared/anti_sycophancy_directive'.
    The .txt extension is added automatically if omitted.
    """
    path = _PROMPTS_DIR / (name if name.endswith(".txt") else name + ".txt")
    return path.read_text(encoding="utf-8").strip()


def load_fmt(name: str, **kwargs) -> str:
    """Load a prompt template and format it with the supplied keyword arguments."""
    return load(name).format(**kwargs)
