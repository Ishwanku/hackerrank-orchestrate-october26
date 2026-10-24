"""Switches used only by evaluation/ablation.py to turn one component off.

GHOST_ABLATE is a comma list; empty (the default) means the full system.
"""
import os

ABLATE = {x.strip() for x in os.environ.get("GHOST_ABLATE", "").split(",") if x.strip()}


def off(name: str) -> bool:
    return name in ABLATE
