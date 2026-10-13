#!/usr/bin/env python3
"""
XuIcons 2.0 Comprehensive Suite Builder (310 Vector Glyph Icons)
Generates developer/scripts/build_xu_icons.py and compiles all fonts and web assets
"""

import os
import sys

def get_brand_icons():
    return [
        {"name": "logo", "category": "Brand", "label": "XU 官方品牌图腾",
         "path": "TOTEM_PATH"},
        {"name": "logo-wordmark", "category": "Brand", "label": "XU 官方字标组合",
         "path": "TOTEM_PATH_WM"},
        {"name": "logo-square", "category": "Brand", "label": "XU 官方正方底座图标",
         "path": "rounded_rect_path(100, 100, 800, 800, 180) + ' ' + get_xu_totem_path(0.68, 160, 160)"},
        {"name": "logo-circle", "category": "Brand", "label": "XU 官方圆形徽章图标",
         "path": "circle_path(500, 500, 440) + ' ' + get_xu_totem_path(0.68, 160, 160)"},
        {"name": "seal", "category": "Brand", "label": "【徐】经典印章字标",
         "path": "rounded_rect_frame(120, 120, 760, 760, 100, 60) + ' M 260 260 L 260 740 M 260 500 L 440 500 M 440 260 L 440 740 M 560 260 L 740 260 M 650 260 L 650 740 M 540 740 L 760 740'"},
        {"name": "xuflow", "category": "Brand", "label": "XUFLOW 原生架构流程图",
         "path": "rounded_rect_path(120, 200, 240, 180, 40) + ' ' + rounded_rect_path(640, 200, 240, 180, 40) + ' ' + rounded_rect_path(380, 620, 240, 180, 40) + ' ' + stroke_to_outline((360, 290), (640, 290), 50) + ' ' + stroke_to_outline((500, 290), (500, 620), 50)"},
        {"name": "xupkg", "category": "Brand", "label": "XUPKG 官方包管理器",
         "path": "M 500 120 L 860 300 L 860 700 L 500 880 L 140 700 L 140 300 Z M 500 120 L 500 480 M 500 480 L 860 300 M 500 480 L 140 300 M 500 480 L 500 880"},
        {"name": "xudocs", "category": "Brand", "label": "XUDOCS 交互式文档引擎",
         "path": "M 160 180 L 500 240 L 840 180 L 840 760 L 500 820 L 160 760 Z M 500 240 L 500 820 M 260 360 L 420 380 M 260 480 L 420 500 M 260 600 L 420 620"},
        {"name": "xuui", "category": "Brand", "label": "XUUI 跨平台图形界面引擎",
         "path": "rounded_rect_frame(100, 160, 800, 680, 80, 60) + ' ' + stroke_to_outline((100, 320), (900, 320), 60) + ' ' + circle_path(220, 240, 30) + ' ' + circle_path(320, 240, 30) + ' ' + circle_path(420, 240, 30) + ' ' + rounded_rect_path(240, 440, 220, 260, 30) + ' ' + rounded_rect_path(540, 440, 220, 260, 30)'"},
        {"name": "xuaot", "category": "Brand", "label": "超音速 AOT 原生编译器",
         "path": "ring_path(500, 500, 440, 360) + ' M 560 140 L 260 520 L 520 520 L 440 860 L 740 460 L 480 460 Z'"},
        {"name": "xuvm", "category": "Brand", "label": "XU-MIR 原生执行引擎",
         "path": "ring_path(500, 500, 440, 360) + ' ' + rounded_rect_path(300, 300, 400, 400, 60) + ' ' + circle_path(500, 500, 80)"},
        {"name": "xulsp", "category": "Brand", "label": "语言服务器协议 (XU-LSP)",
         "path": "circle_path(260, 500, 120) + ' ' + circle_path(740, 500, 120) + ' ' + stroke_to_outline((260, 500), (740, 500), 70) + ' ' + stroke_to_outline((500, 220), (500, 780), 70)"},
        {"name": "xudbg", "category": "Brand", "label": "XU 原生符号调试器",
         "path": "circle_path(500, 500, 380) + ' ' + circle_path(500, 500, 180) + ' ' + stroke_to_outline((120, 500), (880, 500), 50) + ' ' + stroke_to_outline((500, 120), (500, 880), 50)"},
        {"name": "xutest", "category": "Brand", "label": "单元与集成测试框架",
         "path": "M 280 200 L 720 200 L 720 320 L 620 440 L 620 800 L 380 800 L 380 440 L 280 320 Z M 380 580 L 620 580"},
        {"name": "xubench", "category": "Brand", "label": "微基准性能测试套件",
         "path": "ring_path(500, 540, 380, 300) + ' ' + stroke_to_outline((500, 540), (700, 340), 60) + ' ' + circle_path(500, 540, 80)"}
    ]

print("Brand module ready")
