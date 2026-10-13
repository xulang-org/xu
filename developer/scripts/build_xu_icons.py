#!/usr/bin/env python3
"""
XuIcons Master Generator (XU 官方高精字体图标库 v2.0.0)
Total Icons: 370 Comprehensive Icons across 11 Essential Categories
"""

import os
import sys
import json
import base64
import math
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import SVGPath

# Add current directory to path for loading icon definitions
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import icons_data_definitions

UPM = 1000
ASCENDER = 850
DESCENDER = -150

def stroke_to_outline(p1, p2, width):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0: return ""
    nx = -dy / length * (width / 2.0)
    ny = dx / length * (width / 2.0)
    r = width / 2.0
    a = (p1[0] + nx, p1[1] + ny)
    b = (p2[0] + nx, p2[1] + ny)
    c = (p2[0] - nx, p2[1] - ny)
    d = (p1[0] - nx, p1[1] - ny)
    return f"M {a[0]:.1f} {a[1]:.1f} L {b[0]:.1f} {b[1]:.1f} A {r:.1f} {r:.1f} 0 0 1 {c[0]:.1f} {c[1]:.1f} L {d[0]:.1f} {d[1]:.1f} A {r:.1f} {r:.1f} 0 0 1 {a[0]:.1f} {a[1]:.1f} Z"

def circle_path(cx, cy, r):
    return f"M {cx} {cy-r} A {r} {r} 0 1 1 {cx} {cy+r} A {r} {r} 0 1 1 {cx} {cy-r} Z"

def ring_path(cx, cy, r_out, r_in):
    return f"M {cx} {cy-r_out} A {r_out} {r_out} 0 1 1 {cx} {cy+r_out} A {r_out} {r_out} 0 1 1 {cx} {cy-r_out} Z M {cx} {cy-r_in} A {r_in} {r_in} 0 1 0 {cx} {cy+r_in} A {r_in} {r_in} 0 1 0 {cx} {cy-r_in} Z"

def rounded_rect_path(x, y, w, h, r):
    return f"M {x+r} {y} L {x+w-r} {y} A {r} {r} 0 0 1 {x+w} {y+r} L {x+w} {y+h-r} A {r} {r} 0 0 1 {x+w-r} {y+h} L {x+r} {y+h} A {r} {r} 0 0 1 {x} {y+h-r} L {x} {y+r} A {r} {r} 0 0 1 {x+r} {y} Z"

def rounded_rect_frame(x, y, w, h, r, thickness):
    t = thickness
    out_d = f"M {x+r} {y} L {x+w-r} {y} A {r} {r} 0 0 1 {x+w} {y+r} L {x+w} {y+h-r} A {r} {r} 0 0 1 {x+w-r} {y+h} L {x+r} {y+h} A {r} {r} 0 0 1 {x} {y+h-r} L {x} {y+r} A {r} {r} 0 0 1 {x+r} {y} Z"
    ri = max(1, r - t)
    xi = x + t
    yi = y + t
    wi = w - 2*t
    hi = h - 2*t
    in_d = f"M {xi+ri} {yi} A {ri} {ri} 0 0 0 {xi} {yi+ri} L {xi} {yi+hi-ri} A {ri} {ri} 0 0 0 {xi+ri} {yi+hi} L {xi+wi-ri} {yi+hi} A {ri} {ri} 0 0 0 {xi+wi} {yi+hi-ri} L {xi+wi} {yi+ri} A {ri} {ri} 0 0 0 {xi+wi-ri} {yi} Z"
    return out_d + " " + in_d

def get_xu_totem_path(scale=1.0, tx=0, ty=0):
    w = 56 * scale
    # 1. 坚固平底 U 型外框: (105, 140) -> (90, 295) -> (250, 370) -> (410, 295) -> (395, 140)
    c1 = stroke_to_outline((210*scale+tx, 280*scale+ty), (180*scale+tx, 590*scale+ty), w)
    c2 = stroke_to_outline((180*scale+tx, 590*scale+ty), (500*scale+tx, 740*scale+ty), w)
    c3 = stroke_to_outline((500*scale+tx, 740*scale+ty), (820*scale+tx, 590*scale+ty), w)
    c4 = stroke_to_outline((820*scale+tx, 590*scale+ty), (790*scale+tx, 280*scale+ty), w)

    # 2. 内部左向心折线 >: (165, 155) -> (230, 218) -> (165, 280)
    l1 = stroke_to_outline((330*scale+tx, 310*scale+ty), (460*scale+tx, 436*scale+ty), w)
    l2 = stroke_to_outline((460*scale+tx, 436*scale+ty), (330*scale+tx, 560*scale+ty), w)

    # 3. 内部右向心折线 <: (335, 155) -> (270, 218) -> (335, 280)
    r1 = stroke_to_outline((670*scale+tx, 310*scale+ty), (540*scale+tx, 436*scale+ty), w)
    r2 = stroke_to_outline((540*scale+tx, 436*scale+ty), (670*scale+tx, 560*scale+ty), w)

    return f"{c1} {c2} {c3} {c4} {l1} {l2} {r1} {r2}"

def arc_ribbon(cx, cy, r, a1_deg, a2_deg, width):
    t = width / 2.0
    r_out = r + t
    r_in = max(1.0, r - t)

    a1 = math.radians(a1_deg)
    a2 = math.radians(a2_deg)

    p1_out = (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1))
    p1_in  = (cx + r_in  * math.cos(a1), cy + r_in  * math.sin(a1))

    p2_out = (cx + r_out * math.cos(a2), cy + r_out * math.sin(a2))
    p2_in  = (cx + r_in  * math.cos(a2), cy + r_in  * math.sin(a2))

    da = (a2_deg - a1_deg) % 360
    large_arc = 1 if da > 180 else 0
    cap_r = t

    return (f"M {p1_out[0]:.1f} {p1_out[1]:.1f} "
            f"A {r_out:.1f} {r_out:.1f} 0 {large_arc} 1 {p2_out[0]:.1f} {p2_out[1]:.1f} "
            f"A {cap_r:.1f} {cap_r:.1f} 0 0 1 {p2_in[0]:.1f} {p2_in[1]:.1f} "
            f"A {r_in:.1f} {r_in:.1f} 0 {large_arc} 0 {p1_in[0]:.1f} {p1_in[1]:.1f} "
            f"A {cap_r:.1f} {cap_r:.1f} 0 0 1 {p1_out[0]:.1f} {p1_out[1]:.1f} Z")

HELPERS = {
    'stroke': stroke_to_outline,
    'circle': circle_path,
    'ring': ring_path,
    'rect': rounded_rect_path,
    'frame': rounded_rect_frame,
    'totem': get_xu_totem_path,
    'arc': arc_ribbon
}

ICONS = icons_data_definitions.get_all_icons_data(HELPERS)

def build_font(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    fb = FontBuilder(UPM, isTTF=True)

    glyph_names = [".notdef"] + [icon["name"] for icon in ICONS]
    fb.setupGlyphOrder(glyph_names)

    cmap = {}
    for icon in ICONS:
        cmap[icon["code"]] = icon["name"]
    fb.setupCharacterMap(cmap)

    glyphs = {}
    hmetrics = {}

    pen = TTGlyphPen(None)
    qu_pen = Cu2QuPen(pen, max_err=1.0)
    qu_pen.moveTo((200, 0))
    qu_pen.lineTo((200, 700))
    qu_pen.lineTo((800, 700))
    qu_pen.lineTo((800, 0))
    qu_pen.closePath()
    glyphs[".notdef"] = pen.glyph()
    hmetrics[".notdef"] = (1000, 100)

    for icon in ICONS:
        pen = TTGlyphPen(None)
        qu_pen = Cu2QuPen(pen, max_err=1.0)

        try:
            svg_path = SVGPath.fromstring(f'<path d="{icon["path"]}"/>')
            bp = BoundsPen(None)
            svg_path.draw(bp)
            if bp.bounds:
                xmin, ymin, xmax, ymax = bp.bounds
                w = xmax - xmin
                h = ymax - ymin
                xc = (xmin + xmax) / 2.0
                yc = (ymin + ymax) / 2.0
                max_dim = max(w, h)
                scale = 860.0 / max_dim if max_dim > 0 else 0.86
                tx = 500.0 - xc * scale
                ty = 350.0 + yc * scale
            else:
                scale = 0.86
                tx = 50.0
                ty = 780.0

            tpen = TransformPen(qu_pen, (scale, 0, 0, -scale, tx, ty))
            svg_path.draw(tpen)
            glyph = pen.glyph()
        except Exception as e:
            print(f"Error parsing glyph {icon['name']}: {e}")
            glyph = pen.glyph()

        glyphs[icon["name"]] = glyph
        hmetrics[icon["name"]] = (1000, int(tx) if bp.bounds else 50)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(hmetrics)
    fb.setupHorizontalHeader(ascent=ASCENDER, descent=DESCENDER)
    fb.setupNameTable({
        "familyName": "XuIcons",
        "styleName": "Regular",
        "uniqueFontIdentifier": "2.0.0;XU;XuIcons-Regular",
        "fullName": "XuIcons Regular",
        "version": "Version 2.0.0",
        "psName": "XuIcons-Regular",
        "designer": "XU Language & Design System Core Team",
        "vendorURL": "https://lang.xu",
        "description": "Official Master Icon Font for the XU Programming Language Ecosystem (v2.0.0, 370 glyphs)"
    })
    fb.setupOS2(
        sTypoAscender=ASCENDER,
        sTypoDescender=DESCENDER,
        sTypoLineGap=0,
        usWinAscent=ASCENDER,
        usWinDescent=-DESCENDER,
        sxHeight=500,
        sCapHeight=700,
        fsSelection=0x0040
    )
    fb.setupPost()

    ttf_path = os.path.join(output_dir, "xu-icons.ttf")
    fb.save(ttf_path)
    print(f"  ✓ Saved TTF: {ttf_path} ({os.path.getsize(ttf_path)} bytes)")

    woff_path = os.path.join(output_dir, "xu-icons.woff")
    fb.font.flavor = "woff"
    fb.save(woff_path)
    print(f"  ✓ Saved WOFF: {woff_path} ({os.path.getsize(woff_path)} bytes)")

    svg_path = os.path.join(output_dir, "xu-icons.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" standalone="no"?>\n')
        f.write('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n')
        f.write('<svg xmlns="http://www.w3.org/2000/svg">\n')
        f.write('<metadata>Generated by XuIcons Master Builder v2.0.0</metadata>\n')
        f.write('<defs>\n')
        f.write(f'<font id="XuIcons" horiz-adv-x="{UPM}">\n')
        f.write(f'<font-face font-family="XuIcons" units-per-em="{UPM}" ascent="{ASCENDER}" descent="{DESCENDER}"/>\n')
        f.write('<missing-glyph horiz-adv-x="1000" d="M200 0 L200 700 L800 700 L800 0 Z"/>\n')
        for icon in ICONS:
            code_hex = f"&#x{icon['code']:x};"
            f.write(f'<glyph glyph-name="{icon["name"]}" unicode="{code_hex}" horiz-adv-x="1000" d="{icon["path"]}"/>\n')
        f.write('</font>\n</defs>\n</svg>\n')
    print(f"  ✓ Saved SVG Font: {svg_path} ({os.path.getsize(svg_path)} bytes)")

    with open(woff_path, "rb") as f:
        woff_b64 = base64.b64encode(f.read()).decode("ascii")

    css_path = os.path.join(output_dir, "xu-icons.css")
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(f"""/*!
 * XuIcons v2.0.0 (XU Programming Language Master Icon Font)
 * Total Glyphs: {len(ICONS)} Icons across 11 Essential Categories
 * Designed for High-DPI IDEs, Web Frameworks, AST Visualizers & System GUIs
 */

@font-face {{
  font-family: 'XuIcons';
  src: url('data:font/woff;charset=utf-8;base64,{woff_b64}') format('woff'),
       url('xu-icons.woff') format('woff'),
       url('xu-icons.ttf') format('truetype'),
       url('xu-icons.svg#XuIcons') format('svg');
  font-weight: normal;
  font-style: normal;
  font-display: block;
}}

/* Base Icon Class */
.xi {{
  font-family: 'XuIcons' !important;
  speak: never;
  font-style: normal;
  font-weight: normal;
  font-variant: normal;
  text-transform: none;
  line-height: 1;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  vertical-align: -0.125em;
  font-size: 1.18em;
  letter-spacing: normal;
  text-rendering: auto;
}}

/* Sizing Utilities */
.xi-xs  {{ font-size: 0.75em; }}
.xi-sm  {{ font-size: 0.875em; }}
.xi-lg  {{ font-size: 1.333em; vertical-align: -0.2em; }}
.xi-2x  {{ font-size: 2em; }}
.xi-3x  {{ font-size: 3em; }}
.xi-4x  {{ font-size: 4em; }}
.xi-5x  {{ font-size: 5em; }}
.xi-fw  {{ width: 1.25em; text-align: center; }}

/* Transform & Animation Utilities */
.xi-rotate-90  {{ transform: rotate(90deg); }}
.xi-rotate-180 {{ transform: rotate(180deg); }}
.xi-rotate-270 {{ transform: rotate(270deg); }}
.xi-flip-h     {{ transform: scaleX(-1); }}
.xi-flip-v     {{ transform: scaleY(-1); }}

@keyframes xi-spin {{
  0% {{ transform: rotate(0deg); }}
  100% {{ transform: rotate(360deg); }}
}}
.xi-spin {{
  animation: xi-spin 1s infinite linear;
}}
.xi-pulse {{
  animation: xi-spin 1.2s infinite steps(8);
}}

/* Brand Colors */
.xi-brand   {{ color: var(--xu-brand-cinnabar, #E64A19); }}
.xi-crimson {{ color: var(--xu-brand-crimson, #C2185B); }}
.xi-gold    {{ color: var(--xu-brand-gold, #F57F17); }}
.xi-green   {{ color: #2E7D32; }}
.xi-cyan    {{ color: #00838F; }}
.xi-blue    {{ color: #1565C0; }}
.xi-purple  {{ color: #6A1B9A; }}
.xi-muted   {{ color: var(--xu-text-tertiary, #9E9E9E); }}

/* ==================== Glyph Codepoints ({len(ICONS)}) ==================== */
""")
        for icon in ICONS:
            f.write(f".xi-{icon['name']}:before {{ content: \"\\{icon['code']:x}\"; }}\n")

        # Add popular aliases
        f.write("""
/* Compatibility Aliases */
.xi-crypto:before { content: "\\e91d"; }
.xi-book:before { content: "\\e907"; }
""")

    print(f"  ✓ Saved CSS: {css_path} ({os.path.getsize(css_path)} bytes)")

    json_path = os.path.join(output_dir, "xu-icons.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json_data = {
            "name": "XuIcons",
            "version": "2.0.0",
            "count": len(ICONS),
            "icons": [
                {
                    "name": icon["name"],
                    "code": f"0x{icon['code']:x}",
                    "unicode": f"\\{icon['code']:x}",
                    "category": icon["category"],
                    "label": icon["label"]
                }
                for icon in ICONS
            ]
        }
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved JSON: {json_path} ({os.path.getsize(json_path)} bytes)")

    # Generate Interactive HTML Showroom (100% Self-Contained with Base64 embedded font)
    demo_path = os.path.join(output_dir, "demo.html")
    with open(demo_path, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>XuIcons Master Showroom (v2.0.0 · {len(ICONS)} 款纯矢量图元)</title>
  <link rel="stylesheet" href="fonts/xu-icons.css">
  <link rel="stylesheet" href="xu-icons.css">
  <style>
    @font-face {{
      font-family: 'XuIcons';
      src: url('data:font/woff;charset=utf-8;base64,{woff_b64}') format('woff'),
           url('fonts/xu-icons.woff') format('woff'),
           url('xu-icons.woff') format('woff'),
           url('fonts/xu-icons.ttf') format('truetype'),
           url('xu-icons.ttf') format('truetype');
      font-weight: normal;
      font-style: normal;
      font-display: block;
    }}

    .xi {{
      font-family: 'XuIcons' !important;
      speak: never;
      font-style: normal;
      font-weight: normal;
      font-variant: normal;
      text-transform: none;
      line-height: 1;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      vertical-align: 0;
      letter-spacing: normal;
      text-rendering: auto;
    }}

    .xi-spin {{
      animation: xi-spin-kf 1s infinite linear;
    }}
    @keyframes xi-spin-kf {{
      0% {{ transform: rotate(0deg); }}
      100% {{ transform: rotate(360deg); }}
    }}

    :root {{
      --xu-brand: #E64A19;
      --xu-brand-glow: rgba(230, 74, 25, 0.15);
      --xu-bg: #0A0A0F;
      --xu-surface: #14141E;
      --xu-surface-hover: #1E1E2C;
      --xu-border: #262638;
      --xu-border-highlight: #3D3D56;
      --xu-text: #F8FAFC;
      --xu-text-sec: #94A3B8;
      --xu-radius: 12px;
      --xu-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }}
    [data-theme="light"] {{
      --xu-brand: #BE123C;
      --xu-brand-glow: rgba(190, 18, 60, 0.08);
      --xu-bg: #F8F9FA;
      --xu-surface: #FFFFFF;
      --xu-surface-hover: #F1F3F5;
      --xu-border: #E2E8F0;
      --xu-border-highlight: #CBD5E1;
      --xu-text: #0F172A;
      --xu-text-sec: #64748B;
      --xu-shadow: 0 4px 20px rgba(0,0,0,0.06);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: var(--xu-bg);
      color: var(--xu-text);
      padding: 0 0 60px 0;
      transition: background 0.2s, color 0.2s;
      min-height: 100vh;
    }}

    /* Top Nav Bar */
    .top-nav {{
      background: var(--xu-surface);
      border-bottom: 1px solid var(--xu-border);
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
      padding: 12px 28px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }}
    .nav-left {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .back-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      border-radius: 8px;
      background: var(--xu-bg);
      border: 1px solid var(--xu-border);
      color: var(--xu-text-sec);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      transition: all 0.2s;
    }}
    .back-btn:hover {{
      color: var(--xu-text);
      border-color: var(--xu-brand);
    }}
    .brand-title {{
      font-size: 18px;
      font-weight: 900;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .brand-title span.badge {{
      font-size: 11px;
      background: var(--xu-brand-glow);
      color: var(--xu-brand);
      border: 1px solid var(--xu-brand);
      padding: 2px 8px;
      border-radius: 12px;
      font-weight: 800;
    }}

    /* Hero Banner */
    .hero {{
      max-width: 1400px;
      margin: 32px auto 24px;
      padding: 0 24px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 20px;
    }}
    .hero-text h1 {{
      font-size: 32px;
      font-weight: 900;
      letter-spacing: -0.5px;
    }}
    .hero-text p {{
      color: var(--xu-text-sec);
      font-size: 15px;
      margin-top: 6px;
    }}

    /* Action Controls Toolbar */
    .toolbar {{
      max-width: 1400px;
      margin: 0 auto 24px;
      padding: 0 24px;
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
    }}
    .search-wrap {{
      position: relative;
      flex: 1;
      min-width: 280px;
      max-width: 480px;
    }}
    .search-wrap input {{
      width: 100%;
      padding: 12px 16px 12px 42px;
      border: 1px solid var(--xu-border);
      border-radius: var(--xu-radius);
      background: var(--xu-surface);
      color: var(--xu-text);
      font-size: 14px;
      outline: none;
      transition: all 0.2s;
    }}
    .search-wrap input:focus {{
      border-color: var(--xu-brand);
      box-shadow: 0 0 0 3px var(--xu-brand-glow);
    }}
    .search-wrap i.search-ico {{
      position: absolute;
      left: 14px;
      top: 13px;
      color: var(--xu-text-sec);
      font-size: 16px;
    }}
    .tools-right {{
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .slider-ctrl {{
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      padding: 6px 14px;
      border-radius: var(--xu-radius);
      font-size: 12px;
      color: var(--xu-text-sec);
      font-weight: 700;
    }}
    .slider-ctrl input[type="range"] {{
      width: 100px;
      cursor: pointer;
      accent-color: var(--xu-brand);
    }}
    .color-picker-group {{
      display: flex;
      gap: 6px;
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      padding: 6px 10px;
      border-radius: var(--xu-radius);
    }}
    .color-dot {{
      width: 22px;
      height: 22px;
      border-radius: 50%;
      cursor: pointer;
      border: 2px solid transparent;
      transition: transform 0.2s, border-color 0.2s;
    }}
    .color-dot:hover, .color-dot.active {{
      transform: scale(1.15);
      border-color: var(--xu-text);
    }}
    .theme-btn {{
      padding: 10px 16px;
      border-radius: var(--xu-radius);
      border: 1px solid var(--xu-border);
      background: var(--xu-surface);
      color: var(--xu-text);
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    /* Categories Tabs */
    .cats-container {{
      max-width: 1400px;
      margin: 0 auto 24px;
      padding: 0 24px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .cat-pill {{
      padding: 8px 16px;
      border-radius: 20px;
      border: 1px solid var(--xu-border);
      background: var(--xu-surface);
      color: var(--xu-text-sec);
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .cat-pill.active, .cat-pill:hover {{
      background: var(--xu-brand);
      color: #FFF;
      border-color: var(--xu-brand);
      box-shadow: 0 2px 10px var(--xu-brand-glow);
    }}

    /* Icons Grid */
    .icons-grid {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 0 24px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 16px;
    }}
    .icon-card {{
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      border-radius: var(--xu-radius);
      padding: 24px 16px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
      cursor: pointer;
      transition: all 0.2s;
      position: relative;
      user-select: none;
    }}
    .icon-card:hover {{
      transform: translateY(-4px);
      box-shadow: var(--xu-shadow);
      border-color: var(--xu-brand);
      background: var(--xu-surface-hover);
    }}
    .icon-box {{
      width: 72px;
      height: 72px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 14px;
      line-height: 0;
      text-align: center;
    }}
    .icon-box i.xi {{
      font-size: var(--icon-scale, 38px);
      transition: transform 0.2s;
    }}
    .icon-card:hover .icon-box i.xi {{
      transform: scale(1.18);
    }}
    .card-name {{
      font-size: 13px;
      font-weight: 800;
      color: var(--xu-text);
      text-align: center;
      word-break: break-all;
    }}
    .card-label {{
      font-size: 11px;
      color: var(--xu-text-sec);
      margin-top: 4px;
      text-align: center;
      line-height: 1.3;
    }}
    .card-code {{
      font-size: 11px;
      color: var(--xu-brand);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      margin-top: 6px;
      font-weight: 700;
    }}
    .card-tip {{
      position: absolute;
      top: 8px;
      right: 8px;
      font-size: 10px;
      color: var(--xu-text-sec);
      opacity: 0;
      transition: opacity 0.2s;
    }}
    .icon-card:hover .card-tip {{
      opacity: 1;
    }}

    /* Toast Notification */
    .toast {{
      position: fixed;
      bottom: 30px;
      left: 50%;
      transform: translateX(-50%) translateY(100px);
      background: #181824;
      border: 1px solid var(--xu-brand);
      color: #FFF;
      padding: 12px 28px;
      border-radius: 30px;
      font-weight: 700;
      font-size: 14px;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: transform 0.3s cubic-bezier(0.18, 0.89, 0.32, 1.28);
      z-index: 1000;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    }}
    .toast.show {{
      transform: translateX(-50%) translateY(0);
    }}
  </style>
</head>
<body>
  <!-- Sticky Top Nav -->
  <header class="top-nav">
    <div class="nav-left">
      <a href="index.html" class="back-btn"><i class="xi xi-chevron-left"></i> 返回 VI 设计规范主页</a>
      <div class="brand-title">
        <i class="xi xi-logo" style="color:var(--xu-brand); font-size:22px;"></i>
        <span>XuIcons Master Showroom</span>
        <span class="badge">v2.0.0 · {len(ICONS)} 图元</span>
      </div>
    </div>
    <div class="nav-right">
      <button class="theme-btn" onclick="toggleTheme()"><i class="xi xi-moon"></i> 切换明暗主题</button>
    </div>
  </header>

  <!-- Hero Intro -->
  <section class="hero">
    <div class="hero-text">
      <h1>XuIcons 官方字体图标库工作台</h1>
      <p>100% 纯矢量几何绘制 · OpenType 字符几何居中 · 全域覆盖 {len(ICONS)} 款开发/语言/系统图元 · 点击卡片即可复制 HTML 代码</p>
    </div>
  </section>

  <!-- Interactive Controls Toolbar -->
  <section class="toolbar">
    <div class="search-wrap">
      <i class="xi xi-search search-ico"></i>
      <input type="text" id="search-input" placeholder="输入名称、标签或分类实时检索 (如 code, git, database, flow)...">
    </div>

    <div class="tools-right">
      <div class="slider-ctrl">
        <span>尺寸: <span id="size-val">38px</span></span>
        <input type="range" id="size-range" min="18" max="64" value="38">
      </div>

      <div class="color-picker-group">
        <div class="color-dot active" style="background:#F8FAFC;" onclick="setColor('default', this)" title="默认文本色"></div>
        <div class="color-dot" style="background:#E64A19;" onclick="setColor('#E64A19', this)" title="朱砂红 (Brand)"></div>
        <div class="color-dot" style="background:#2E7D32;" onclick="setColor('#2E7D32', this)" title="翠竹绿 (Success)"></div>
        <div class="color-dot" style="background:#00838F;" onclick="setColor('#00838F', this)" title="天青蓝 (Cyan)"></div>
        <div class="color-dot" style="background:#F57F17;" onclick="setColor('#F57F17', this)" title="向日金 (Gold)"></div>
        <div class="color-dot" style="background:#6A1B9A;" onclick="setColor('#6A1B9A', this)" title="紫棠色 (Purple)"></div>
      </div>
    </div>
  </section>

  <!-- Categories Filter -->
  <nav class="cats-container" id="cats-pills">
    <button class="cat-pill active" onclick="filterCat('all')">全部分类 ({len(ICONS)})</button>
  </nav>

  <!-- Grid Display -->
  <main class="icons-grid" id="icons-grid"></main>

  <!-- Toast -->
  <div class="toast" id="toast-msg">
    <i class="xi xi-check-circle" style="color:#2E7D32; font-size:18px;"></i>
    <span id="toast-text">已复制到剪贴板！</span>
  </div>

  <script>
    const ICONS_DATA = {json.dumps(ICONS, ensure_ascii=False)};

    // Setup categories dynamically
    const catCounts = {{}};
    ICONS_DATA.forEach(i => {{
      catCounts[i.category] = (catCounts[i.category] || 0) + 1;
    }});

    const catsPills = document.getElementById('cats-pills');
    Object.keys(catCounts).forEach(cat => {{
      const pill = document.createElement('button');
      pill.className = 'cat-pill';
      pill.innerText = `${{cat}} (${{catCounts[cat]}})`;
      pill.onclick = () => filterCat(cat);
      catsPills.appendChild(pill);
    }});

    let selectedCat = 'all';
    let searchQuery = '';
    let currentColor = 'default';

    function renderGrid() {{
      const grid = document.getElementById('icons-grid');
      grid.innerHTML = '';

      const filtered = ICONS_DATA.filter(ic => {{
        const catMatch = selectedCat === 'all' || ic.category === selectedCat;
        const q = searchQuery.toLowerCase().trim();
        const qMatch = !q ||
          ic.name.toLowerCase().includes(q) ||
          ic.label.toLowerCase().includes(q) ||
          ic.category.toLowerCase().includes(q) ||
          ic.code.toString(16).includes(q);
        return catMatch && qMatch;
      }});

      if (filtered.length === 0) {{
        grid.innerHTML = `
          <div style="grid-column:1/-1; text-align:center; padding:60px 20px; color:var(--xu-text-sec);">
            <i class="xi xi-search" style="font-size:48px; opacity:0.3; margin-bottom:12px;"></i>
            <p style="font-size:16px; font-weight:700;">未找到匹配 "${{searchQuery}}" 的图标</p>
          </div>
        `;
        return;
      }}

      filtered.forEach(ic => {{
        const card = document.createElement('div');
        card.className = 'icon-card';
        const colorStyle = currentColor !== 'default' ? `style="color:${{currentColor}}"` : '';
        card.innerHTML = `
          <span class="card-tip">点击复制</span>
          <div class="icon-box">
            <i class="xi xi-${{ic.name}}" ${{colorStyle}}></i>
          </div>
          <div class="card-name">${{ic.name}}</div>
          <div class="card-label">${{ic.label}}</div>
          <div class="card-code">0x${{ic.code.toString(16).toUpperCase()}}</div>
        `;
        card.onclick = () => copyCode(ic.name);
        grid.appendChild(card);
      }});
    }}

    function filterCat(cat) {{
      selectedCat = cat;
      document.querySelectorAll('.cat-pill').forEach(p => {{
        p.classList.toggle('active', p.innerText.startsWith(cat === 'all' ? '全部分类' : cat));
      }});
      renderGrid();
    }}

    document.getElementById('search-input').addEventListener('input', (e) => {{
      searchQuery = e.target.value;
      renderGrid();
    }});

    const sizeRange = document.getElementById('size-range');
    const sizeVal = document.getElementById('size-val');
    sizeRange.addEventListener('input', (e) => {{
      const s = e.target.value + 'px';
      sizeVal.innerText = s;
      document.documentElement.style.setProperty('--icon-scale', s);
    }});

    function setColor(color, dotElem) {{
      currentColor = color;
      document.querySelectorAll('.color-dot').forEach(d => d.classList.remove('active'));
      dotElem.classList.add('active');
      renderGrid();
    }}

    function copyCode(name) {{
      const snippet = `<i class="xi xi-${{name}}"></i>`;
      navigator.clipboard.writeText(snippet).then(() => {{
        const toast = document.getElementById('toast-msg');
        document.getElementById('toast-text').innerText = `已复制: ${{snippet}}`;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 2200);
      }});
    }}

    function toggleTheme() {{
      const cur = document.documentElement.getAttribute('data-theme');
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
    }}

    renderGrid();
  </script>
</body>
</html>
""")
    print(f"  ✓ Saved Showroom: {demo_path} ({os.path.getsize(demo_path)} bytes)")

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/Users/dmy/work/xu/brand/fonts/xu-icons"
    print(f"Building XuIcons Master Suite with {len(ICONS)} glyphs into {out}...")
    build_font(out)
