"""Xu brand assets: content mark vs desktop icon.

Canonical sources live in brand/:
  xu_classic.svg / .png  — content (pages, docs, favicon)
  xu_app_logo.svg / .png — desktop (Dock / tray / window / .icns / .ico)

xu_app_icon.png is a copy of xu_app_logo.png for older paths.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ICON_PNG = ROOT / "brand" / "xu_app_logo.png"
CLASSIC_SVG = ROOT / "brand" / "xu_classic.svg"
CLASSIC_PNG = ROOT / "brand" / "xu_classic.png"
# Project brand/ lookup order for the desktop icon blob.
ICON_NAMES = ("icon.png", "xu_app_logo.png", "xu_app_icon.png")


def resolve_project_icon(xu_src: pathlib.Path) -> pathlib.Path:
    """Desktop project: brand/icon.png | xu_app_logo.png | xu_app_icon.png; else repo logo."""
    for name in ICON_NAMES:
        cand = xu_src.parent / "brand" / name
        if cand.is_file():
            return cand
    return ICON_PNG


def brand_www_extras(xu_src: pathlib.Path, icon_png: pathlib.Path) -> list[tuple[str, bytes]]:
    """Embed app brand/ plus classic content mark for xu://app/brand/…."""
    files: dict[str, bytes] = {}
    brand_dir = xu_src.parent / "brand"
    if brand_dir.is_dir():
        for p in sorted(brand_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(brand_dir).as_posix()
            if ".." in rel.split("/"):
                continue
            files["brand/" + rel] = p.read_bytes()
    icon_bytes = icon_png.read_bytes()
    files["brand/xu_app_logo.png"] = icon_bytes
    files["brand/xu_app_icon.png"] = icon_bytes
    if CLASSIC_SVG.is_file():
        files.setdefault("brand/xu_classic.svg", CLASSIC_SVG.read_bytes())
    if CLASSIC_PNG.is_file():
        files.setdefault("brand/xu_classic.png", CLASSIC_PNG.read_bytes())
    return list(files.items())
