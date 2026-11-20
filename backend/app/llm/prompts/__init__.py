"""Versioned prompts. Each `<id>.<version>.md` starts with a front-matter block."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    model_hint: str
    output_schema: str
    text: str

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


@lru_cache
def load_prompt(prompt_id: str, version: str = "v1") -> Prompt:
    raw = (PROMPTS_DIR / f"{prompt_id}.{version}.md").read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"prompt {prompt_id}.{version} has no front matter")
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front)
    if meta.get("id") != prompt_id or meta.get("version") != version:
        raise ValueError(f"prompt {prompt_id}.{version}: front matter id/version mismatch")
    return Prompt(
        id=meta["id"],
        version=meta["version"],
        model_hint=meta["model_hint"],
        output_schema=meta["output_schema"],
        text=body.strip() + "\n",
    )
