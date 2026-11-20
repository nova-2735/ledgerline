"""Invoice templates. Each module exposes TEMPLATE (name, capabilities, render)."""

from __future__ import annotations

from importlib import import_module

from .base import Template

NAMES = ("classic_gst", "modern", "service_letterhead", "small_trader")


def get_template(name: str) -> Template:
    if name not in NAMES:
        raise KeyError(f"unknown template: {name}")
    template: Template = import_module(f"{__name__}.{name}").TEMPLATE
    return template
