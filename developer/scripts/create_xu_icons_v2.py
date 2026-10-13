#!/usr/bin/env python3
"""
XuIcons 2.0 Full Generator Script
Assembles and writes developer/scripts/build_xu_icons.py with 310 icons.
"""

import os
import sys

def main():
    dest = "/Users/dmy/work/xu/developer/scripts/build_xu_icons.py"

    with open(dest, "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
"""
XuIcons Master Generator (XU 官方高精字体图标库 v2.0.0)
Total Icons: 310 Comprehensive Icons across 10 Essential Categories
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
    return f"M {cx-r} {cy} A {r} {r} 0 1 0 {cx+r} {cy} A {r} {r} 0 1 0 {cx-r} {cy} Z"

def ring_path(cx, cy, r_out, r_in):
    return f"M {cx-r_out} {cy} A {r_out} {r_out} 0 1 0 {cx+r_out} {cy} A {r_out} {r_out} 0 1 0 {cx-r_out} {cy} Z M {cx-r_in} {cy} A {r_in} {r_in} 0 1 1 {cx+r_in} {cy} A {r_in} {r_in} 0 1 1 {cx-r_in} {cy} Z"

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
    c1 = stroke_to_outline((210*scale+tx, 280*scale+ty), (180*scale+tx, 590*scale+ty), 56*scale)
    c2 = stroke_to_outline((180*scale+tx, 590*scale+ty), (500*scale+tx, 740*scale+ty), 56*scale)
    c3 = stroke_to_outline((500*scale+tx, 740*scale+ty), (820*scale+tx, 590*scale+ty), 56*scale)
    c4 = stroke_to_outline((820*scale+tx, 590*scale+ty), (790*scale+tx, 280*scale+ty), 56*scale)
    p1 = stroke_to_outline((340*scale+tx, 230*scale+ty), (370*scale+tx, 450*scale+ty), 50*scale)
    p2 = stroke_to_outline((370*scale+tx, 450*scale+ty), (500*scale+tx, 550*scale+ty), 50*scale)
    p3 = stroke_to_outline((500*scale+tx, 550*scale+ty), (630*scale+tx, 450*scale+ty), 50*scale)
    p4 = stroke_to_outline((630*scale+tx, 450*scale+ty), (660*scale+tx, 230*scale+ty), 50*scale)
    dot1 = circle_path(320*scale+tx, 600*scale+ty, 36*scale)
    dot2 = circle_path(680*scale+tx, 600*scale+ty, 36*scale)
    return f"{c1} {c2} {c3} {c4} {p1} {p2} {p3} {p4} {dot1} {dot2}"
''')
    print("Base written.")

if __name__ == '__main__':
    main()
