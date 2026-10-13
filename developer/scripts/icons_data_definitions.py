#!/usr/bin/env python3
"""
XuIcons Complete Vector Definitions v2.1.0 (Zero Open Contours Guarantee)
All 370 icons use 100% closed 2D filled outlines, frames, ribbons and polygons.
"""

def get_brand_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    totem = helpers['totem']
    arc = helpers['arc']

    return [
        {"name": "logo", "category": "Brand", "label": "XU 官方品牌图腾", "path": totem(1.0, 0, 0)},
        {"name": "logo-wordmark", "category": "Brand", "label": "XU 官方字标组合", "path": totem(0.82, 90, -100) + " " + stroke((340, 680), (450, 830), 42) + " " + stroke((450, 680), (340, 830), 42) + " " + stroke((550, 680), (550, 770), 42) + " " + stroke((660, 680), (660, 770), 42) + " M 529 770 A 65.5 65.5 0 0 0 681 770 L 639 770 A 23.5 23.5 0 0 1 571 770 Z"},
        {"name": "logo-square", "category": "Brand", "label": "XU 官方正方底座图标", "path": rect(100, 100, 800, 800, 180) + " " + totem(0.68, 160, 160)},
        {"name": "logo-circle", "category": "Brand", "label": "XU 官方圆形徽章图标", "path": circle(500, 500, 440) + " " + totem(0.68, 160, 160)},
        {"name": "seal", "category": "Brand", "label": "【徐】经典印章字标", "path": frame(120, 120, 760, 760, 100, 60) + " " + stroke((260, 260), (260, 740), 45) + " " + stroke((260, 500), (440, 500), 45) + " " + stroke((440, 260), (440, 740), 45) + " " + stroke((560, 260), (740, 260), 45) + " " + stroke((650, 260), (650, 740), 45) + " " + stroke((540, 740), (760, 740), 45)},
        {"name": "xuflow", "category": "Brand", "label": "XUFLOW 原生架构流程图", "path": rect(120, 200, 240, 180, 40) + " " + rect(640, 200, 240, 180, 40) + " " + rect(380, 620, 240, 180, 40) + " " + stroke((360, 290), (640, 290), 50) + " " + stroke((500, 290), (500, 620), 50)},
        {"name": "xupkg", "category": "Brand", "label": "XUPKG 官方包管理器", "path": frame(140, 200, 720, 600, 60, 50) + " " + stroke((140, 200), (500, 500), 45) + " " + stroke((860, 200), (500, 500), 45) + " " + stroke((500, 500), (500, 800), 45)},
        {"name": "xudocs", "category": "Brand", "label": "XUDOCS 交互式文档引擎", "path": frame(160, 180, 680, 640, 60, 50) + " " + stroke((500, 180), (500, 820), 50) + " " + stroke((240, 360), (420, 360), 40) + " " + stroke((240, 480), (420, 480), 40) + " " + stroke((240, 600), (420, 600), 40) + " " + stroke((580, 360), (760, 360), 40) + " " + stroke((580, 480), (760, 480), 40)},
        {"name": "xuui", "category": "Brand", "label": "XUUI 跨平台图形界面引擎", "path": frame(100, 160, 800, 680, 80, 60) + " " + stroke((100, 320), (900, 320), 60) + " " + circle(220, 240, 30) + " " + circle(320, 240, 30) + " " + circle(420, 240, 30) + " " + rect(240, 440, 220, 260, 30) + " " + rect(540, 440, 220, 260, 30)},
        {"name": "xuaot", "category": "Brand", "label": "超音速 AOT 原生编译器", "path": ring(500, 500, 440, 360) + " M 560 140 L 260 520 L 520 520 L 440 860 L 740 460 L 480 460 Z"},
        {"name": "xuvm", "category": "Brand", "label": "XU-MIR 原生执行引擎", "path": ring(500, 500, 440, 360) + " " + rect(300, 300, 400, 400, 60) + " " + circle(500, 500, 80)},
        {"name": "xulsp", "category": "Brand", "label": "语言服务器协议 (XU-LSP)", "path": circle(260, 500, 120) + " " + circle(740, 500, 120) + " " + stroke((260, 500), (740, 500), 70) + " " + stroke((500, 220), (500, 780), 70)},
        {"name": "xudbg", "category": "Brand", "label": "XU 原生符号调试器", "path": circle(500, 500, 380) + " " + circle(500, 500, 180) + " " + stroke((120, 500), (880, 500), 50) + " " + stroke((500, 120), (500, 880), 50)},
        {"name": "xutest", "category": "Brand", "label": "单元与集成测试框架", "path": stroke((280, 200), (720, 200), 50) + " " + stroke((280, 200), (280, 340), 50) + " " + stroke((720, 200), (720, 340), 50) + " " + stroke((280, 340), (380, 480), 50) + " " + stroke((720, 340), (620, 480), 50) + " " + stroke((380, 480), (380, 800), 50) + " " + stroke((620, 480), (620, 800), 50) + " " + stroke((380, 800), (620, 800), 50) + " " + stroke((420, 600), (580, 600), 40)},
        {"name": "xubench", "category": "Brand", "label": "微基准性能测试套件", "path": ring(500, 540, 380, 300) + " " + stroke((500, 540), (700, 340), 60) + " " + circle(500, 540, 80)}
    ]

def get_language_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "bolt", "category": "Language", "label": "极速闪电构建", "path": "M 560 100 L 220 540 L 500 540 L 440 900 L 780 460 L 500 460 Z"},
        {"name": "ownership", "category": "Language", "label": "独占所有权模型", "path": ring(500, 340, 200, 120) + " " + rect(220, 440, 560, 440, 80) + " " + circle(500, 620, 50) + " " + stroke((500, 620), (500, 740), 40)},
        {"name": "borrow", "category": "Language", "label": "只读共享借用 &T", "path": stroke((350, 220), (650, 220), 80) + " " + stroke((650, 220), (350, 780), 80) + " " + stroke((350, 780), (650, 780), 80)},
        {"name": "borrow-mut", "category": "Language", "label": "独占可变借用 mut &T", "path": stroke((280, 220), (580, 220), 80) + " " + stroke((580, 220), (280, 780), 80) + " " + stroke((280, 780), (580, 780), 80) + " M 780 260 L 680 480 L 800 480 L 730 700 L 880 440 L 780 440 Z"},
        {"name": "affine", "category": "Language", "label": "仿射类型保证零泄漏", "path": ring(500, 500, 420, 340) + " " + stroke((280, 500), (720, 500), 70) + " " + stroke((500, 280), (500, 720), 70)},
        {"name": "move", "category": "Language", "label": "所有权移交返回 <<", "path": stroke((480, 260), (220, 500), 70) + " " + stroke((220, 500), (480, 740), 70) + " " + stroke((760, 260), (500, 500), 70) + " " + stroke((500, 500), (760, 740), 70)},
        {"name": "clone", "category": "Language", "label": "显式克隆复制", "path": rect(340, 340, 460, 460, 60) + " " + frame(200, 200, 460, 460, 60, 60)},
        {"name": "copy-val", "category": "Language", "label": "值语义隐式复制", "path": circle(360, 500, 180) + " " + circle(640, 500, 180) + " " + stroke((360, 500), (640, 500), 40)},
        {"name": "destruct", "category": "Language", "label": "确定性析构 Drop", "path": frame(160, 160, 680, 680, 80, 60) + " " + stroke((320, 320), (680, 680), 70) + " " + stroke((680, 320), (320, 680), 70)},
        {"name": "drop", "category": "Language", "label": "资源释放 (Drop)", "path": frame(200, 300, 600, 520, 60, 50) + " " + stroke((160, 300), (840, 300), 50) + " " + stroke((360, 420), (360, 700), 40) + " " + stroke((500, 420), (500, 700), 40) + " " + stroke((640, 420), (640, 700), 40) + " " + frame(380, 180, 240, 120, 20, 30)},
        {"name": "lifetime", "category": "Language", "label": "生命周期作用域 'a", "path": ring(500, 500, 420, 340) + " " + stroke((500, 500), (500, 240), 60) + " " + stroke((500, 500), (700, 500), 60)},
        {"name": "leak", "category": "Language", "label": "防内存泄漏防护", "path": frame(200, 200, 600, 600, 80, 60) + " " + circle(500, 500, 60) + " " + stroke((500, 320), (500, 400), 50) + " " + stroke((500, 600), (500, 680), 50)},
        {"name": "flow", "category": "Language", "label": "流程控制流", "path": circle(260, 260, 100) + " " + circle(740, 260, 100) + " " + circle(500, 740, 100) + " " + stroke((260, 260), (500, 740), 50) + " " + stroke((740, 260), (500, 740), 50)},
        {"name": "coroutine", "category": "Language", "label": "轻量级协程并发 xu", "path": stroke((200, 320), (700, 320), 70) + " M 650 200 L 860 320 L 650 440 Z " + stroke((800, 680), (300, 680), 70) + " M 350 560 L 140 680 L 350 800 Z"},
        {"name": "channel", "category": "Language", "label": "类型化无锁通道 chan", "path": frame(120, 300, 760, 400, 80, 60) + " " + circle(320, 500, 60) + " " + circle(500, 500, 60) + " " + circle(680, 500, 60)},
        {"name": "immutable", "category": "Language", "label": "默认不可变 (Const)", "path": ring(500, 500, 400, 320) + " " + stroke((280, 500), (720, 500), 70)},
        {"name": "mutable", "category": "Language", "label": "显式可变声明 mut", "path": stroke((200, 500), (800, 500), 70) + " " + stroke((500, 200), (500, 800), 70)},
        {"name": "closure", "category": "Language", "label": "匿名函数与闭包", "path": ring(380, 500, 260, 180) + " " + ring(620, 500, 260, 180)},
        {"name": "generic", "category": "Language", "label": "泛型多态 [T]", "path": stroke((300, 220), (180, 220), 60) + " " + stroke((180, 220), (180, 780), 60) + " " + stroke((180, 780), (300, 780), 60) + " " + stroke((700, 220), (820, 220), 60) + " " + stroke((820, 220), (820, 780), 60) + " " + stroke((820, 780), (700, 780), 60) + " " + stroke((380, 340), (620, 340), 60) + " " + stroke((500, 340), (500, 660), 60)},
        {"name": "interface", "category": "Language", "label": "接口抽象定义", "path": ring(500, 500, 400, 320) + " " + circle(500, 500, 120)},
        {"name": "struct", "category": "Language", "label": "结构体复合数据", "path": frame(160, 160, 680, 680, 60, 50) + " " + stroke((160, 380), (840, 380), 50) + " " + stroke((160, 600), (840, 600), 50)},
        {"name": "enum", "category": "Language", "label": "代数枚举类型", "path": circle(260, 300, 90) + " " + circle(740, 300, 90) + " " + circle(500, 700, 90) + " " + stroke((260, 300), (740, 300), 40) + " " + stroke((740, 300), (500, 700), 40) + " " + stroke((500, 700), (260, 300), 40)},
        {"name": "pointer", "category": "Language", "label": "安全托管引用", "path": stroke((200, 800), (650, 350), 70) + " M 520 220 L 800 200 L 780 480 Z"},
        {"name": "macro", "category": "Language", "label": "宏与元编程 #meta", "path": stroke((340, 160), (340, 840), 70) + " " + stroke((660, 160), (660, 840), 70) + " " + stroke((160, 340), (840, 340), 70) + " " + stroke((160, 660), (840, 660), 70)},
        {"name": "safety", "category": "Language", "label": "编译期安全证明 #safety", "path": frame(160, 160, 680, 680, 80, 60) + " " + stroke((320, 500), (460, 640), 70) + " " + stroke((460, 640), (680, 380), 70)},
        {"name": "throw", "category": "Language", "label": "错误抛出 >>", "path": stroke((240, 260), (500, 500), 70) + " " + stroke((500, 500), (240, 740), 70) + " " + stroke((520, 260), (780, 500), 70) + " " + stroke((780, 500), (520, 740), 70)},
        {"name": "catch", "category": "Language", "label": "错误捕获 (or)", "path": frame(160, 240, 680, 520, 60, 50) + " " + stroke((340, 500), (660, 500), 60) + " " + stroke((500, 340), (500, 660), 60)},
        {"name": "return", "category": "Language", "label": "零成本返回 <<", "path": stroke((480, 260), (220, 500), 70) + " " + stroke((220, 500), (480, 740), 70) + " " + stroke((760, 260), (500, 500), 70) + " " + stroke((500, 500), (760, 740), 70)},
        {"name": "break", "category": "Language", "label": "循环中断 <-", "path": stroke((760, 500), (240, 500), 70) + " M 420 320 L 220 500 L 420 680 Z"},
        {"name": "continue", "category": "Language", "label": "循环推进 ->", "path": stroke((240, 500), (760, 500), 70) + " M 580 320 L 780 500 L 580 680 Z"},
        {"name": "yield", "category": "Language", "label": "协程让出执行权", "path": stroke((200, 500), (640, 500), 60) + " " + stroke((640, 500), (640, 260), 60) + " M 520 380 L 640 240 L 760 380 Z " + arc(500, 600, 200, 0, 180, 50)},
        {"name": "await", "category": "Language", "label": "异步挂起等待", "path": ring(500, 500, 380, 300) + " " + stroke((500, 260), (500, 500), 60) + " " + stroke((500, 500), (680, 500), 60)},
        {"name": "async", "category": "Language", "label": "原生异步任务 async", "path": stroke((200, 340), (800, 340), 60) + " " + stroke((200, 500), (650, 500), 60) + " " + stroke((200, 660), (500, 660), 60)},
        {"name": "match", "category": "Language", "label": "模式匹配表达式", "path": stroke((180, 280), (440, 280), 60) + " " + stroke((180, 500), (440, 500), 60) + " " + stroke((180, 720), (440, 720), 60) + " " + stroke((600, 360), (780, 500), 60) + " " + stroke((600, 640), (780, 500), 60)}
    ]

def get_compiler_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "terminal", "category": "Compiler", "label": "编译器命令行 xu", "path": frame(120, 160, 760, 680, 80, 60) + " " + stroke((240, 340), (380, 480), 60) + " " + stroke((380, 480), (240, 620), 60) + " " + stroke((440, 620), (660, 620), 60)},
        {"name": "cpu", "category": "Compiler", "label": "CPU 处理器与原生机器码", "path": frame(220, 220, 560, 560, 80, 60) + " " + rect(360, 360, 280, 280, 40) + " " + stroke((340, 100), (340, 220), 50) + " " + stroke((500, 100), (500, 220), 50) + " " + stroke((660, 100), (660, 220), 50) + " " + stroke((340, 780), (340, 900), 50) + " " + stroke((500, 780), (500, 900), 50) + " " + stroke((660, 780), (660, 900), 50) + " " + stroke((100, 340), (220, 340), 50) + " " + stroke((100, 500), (220, 500), 50) + " " + stroke((100, 660), (220, 660), 50) + " " + stroke((780, 340), (900, 340), 50) + " " + stroke((780, 500), (900, 500), 50) + " " + stroke((780, 660), (900, 660), 50)},
        {"name": "memory", "category": "Compiler", "label": "内存管理堆栈", "path": frame(140, 240, 720, 520, 60, 60) + " " + rect(220, 340, 100, 140, 20) + " " + rect(380, 340, 100, 140, 20) + " " + rect(540, 340, 100, 140, 20) + " " + rect(700, 340, 80, 140, 20) + " " + stroke((200, 760), (200, 840), 40) + " " + stroke((320, 760), (320, 840), 40) + " " + stroke((440, 760), (440, 840), 40) + " " + stroke((560, 760), (560, 840), 40) + " " + stroke((680, 760), (680, 840), 40) + " " + stroke((800, 760), (800, 840), 40)},
        {"name": "mir", "category": "Compiler", "label": "MIR 中间表示", "path": rect(160, 180, 280, 180, 30) + " " + rect(560, 180, 280, 180, 30) + " " + rect(360, 640, 280, 180, 30) + " " + stroke((300, 360), (460, 640), 50) + " " + stroke((700, 360), (540, 640), 50)},
        {"name": "ast", "category": "Compiler", "label": "语法抽象语法树 (AST)", "path": circle(500, 180, 80) + " " + circle(260, 480, 70) + " " + circle(740, 480, 70) + " " + circle(160, 780, 60) + " " + circle(360, 780, 60) + " " + circle(640, 780, 60) + " " + circle(840, 780, 60) + " " + stroke((500, 180), (260, 480), 40) + " " + stroke((500, 180), (740, 480), 40) + " " + stroke((260, 480), (160, 780), 40) + " " + stroke((260, 480), (360, 780), 40) + " " + stroke((740, 480), (640, 780), 40) + " " + stroke((740, 480), (840, 780), 40)},
        {"name": "token", "category": "Compiler", "label": "词法 Token 流", "path": rect(140, 340, 180, 320, 40) + " " + rect(410, 340, 180, 320, 40) + " " + rect(680, 340, 180, 320, 40)},
        {"name": "binary", "category": "Compiler", "label": "二进制原生机器码", "path": stroke((300, 200), (300, 500), 60) + " " + ring(700, 350, 150, 90) + " " + ring(300, 650, 150, 90) + " " + stroke((700, 500), (700, 800), 60)},
        {"name": "asm", "category": "Compiler", "label": "底层汇编指令", "path": stroke((200, 240), (800, 240), 60) + " " + stroke((200, 420), (620, 420), 60) + " " + stroke((200, 600), (740, 600), 60) + " " + stroke((200, 780), (500, 780), 60)},
        {"name": "bytecode", "category": "Compiler", "label": "字节码执行指令", "path": rect(180, 180, 280, 280, 40) + " " + rect(540, 180, 280, 280, 40) + " " + rect(180, 540, 280, 280, 40) + " " + ring(680, 680, 140, 80)},
        {"name": "stack", "category": "Compiler", "label": "调用栈内存帧", "path": rect(200, 660, 600, 160, 30) + " " + rect(240, 440, 520, 160, 30) + " " + rect(280, 220, 440, 160, 30)},
        {"name": "heap", "category": "Compiler", "label": "堆内存分配", "path": circle(340, 400, 160) + " " + circle(660, 400, 160) + " " + circle(500, 680, 160) + " " + stroke((340, 400), (660, 400), 40) + " " + stroke((660, 400), (500, 680), 40) + " " + stroke((500, 680), (340, 400), 40)},
        {"name": "gc-free", "category": "Compiler", "label": "零 GC 开销", "path": ring(500, 500, 400, 320) + " " + stroke((220, 220), (780, 780), 70)},
        {"name": "thread", "category": "Compiler", "label": "原生系统级线程", "path": stroke((300, 200), (300, 800), 50) + " " + stroke((500, 140), (500, 860), 50) + " " + stroke((700, 200), (700, 800), 50) + " " + circle(300, 200, 40) + " " + circle(500, 140, 40) + " " + circle(700, 200, 40)},
        {"name": "mutex", "category": "Compiler", "label": "互斥同步锁 Mutex", "path": ring(500, 380, 220, 140) + " " + frame(240, 460, 520, 400, 60, 50) + " " + circle(500, 660, 50)},
        {"name": "atomic", "category": "Compiler", "label": "原子无锁操作 Atomic", "path": circle(500, 500, 100) + " " + ring(500, 500, 360, 300) + " " + stroke((200, 500), (800, 500), 40) + " " + stroke((500, 200), (500, 800), 40)},
        {"name": "process", "category": "Compiler", "label": "独立系统进程", "path": frame(160, 160, 680, 680, 80, 60) + " " + rect(260, 260, 480, 480, 40) + " " + circle(500, 500, 80)}
    ]

def get_devtools_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "code", "category": "DevTools", "label": "代码符号 </>", "path": stroke((340, 240), (180, 500), 70) + " " + stroke((180, 500), (340, 760), 70) + " " + stroke((660, 240), (820, 500), 70) + " " + stroke((820, 500), (660, 760), 70) + " " + stroke((580, 200), (420, 800), 60)},
        {"name": "code-block", "category": "DevTools", "label": "代码块容器", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((300, 340), (220, 460), 50) + " " + stroke((220, 460), (300, 580), 50) + " " + stroke((440, 340), (520, 460), 50) + " " + stroke((520, 460), (440, 580), 50) + " " + stroke((620, 600), (740, 600), 50)},
        {"name": "terminal-box", "category": "DevTools", "label": "内嵌终端", "path": frame(140, 200, 720, 600, 60, 50) + " " + stroke((240, 360), (360, 480), 50) + " " + stroke((360, 480), (240, 600), 50) + " " + stroke((420, 600), (640, 600), 50)},
        {"name": "curly-braces", "category": "DevTools", "label": "花括号作用域 { }", "path": stroke((360, 200), (280, 200), 60) + " " + stroke((280, 200), (280, 440), 60) + " " + stroke((280, 440), (200, 500), 60) + " " + stroke((200, 500), (280, 560), 60) + " " + stroke((280, 560), (280, 800), 60) + " " + stroke((280, 800), (360, 800), 60) + " " + stroke((640, 200), (720, 200), 60) + " " + stroke((720, 200), (720, 440), 60) + " " + stroke((720, 440), (800, 500), 60) + " " + stroke((800, 500), (720, 560), 60) + " " + stroke((720, 560), (720, 800), 60) + " " + stroke((720, 800), (640, 800), 60)},
        {"name": "brackets", "category": "DevTools", "label": "方括号 [ ]", "path": stroke((360, 200), (240, 200), 70) + " " + stroke((240, 200), (240, 800), 70) + " " + stroke((240, 800), (360, 800), 70) + " " + stroke((640, 200), (760, 200), 70) + " " + stroke((760, 200), (760, 800), 70) + " " + stroke((760, 800), (640, 800), 70)},
        {"name": "parentheses", "category": "DevTools", "label": "圆括号 ( )", "path": arc(380, 500, 300, 120, 240, 60) + " " + arc(620, 500, 300, 300, 420, 60)},
        {"name": "hash-tag", "category": "DevTools", "label": "库与命名空间 #pkg", "path": stroke((360, 160), (360, 840), 70) + " " + stroke((640, 160), (640, 840), 70) + " " + stroke((160, 360), (840, 360), 70) + " " + stroke((160, 640), (840, 640), 70)},
        {"name": "at-symbol", "category": "DevTools", "label": "装饰器与元数据 @", "path": ring(500, 500, 140, 80) + " " + arc(500, 500, 320, 0, 270, 60) + " " + stroke((640, 500), (640, 700), 60)},
        {"name": "indent", "category": "DevTools", "label": "增加代码缩进", "path": stroke((160, 240), (840, 240), 60) + " " + stroke((420, 420), (840, 420), 60) + " " + stroke((420, 600), (840, 600), 60) + " " + stroke((160, 780), (840, 780), 60) + " M 180 400 L 320 510 L 180 620 Z"},
        {"name": "outdent", "category": "DevTools", "label": "减少代码缩进", "path": stroke((160, 240), (840, 240), 60) + " " + stroke((420, 420), (840, 420), 60) + " " + stroke((420, 600), (840, 600), 60) + " " + stroke((160, 780), (840, 780), 60) + " M 320 400 L 180 510 L 320 620 Z"},
        {"name": "cursor", "category": "DevTools", "label": "IDE 编辑光标", "path": "M 200 160 L 400 840 L 520 580 L 780 580 Z"},
        {"name": "selection", "category": "DevTools", "label": "高亮选区", "path": frame(160, 200, 680, 600, 60, 50) + " " + rect(260, 320, 480, 360, 30)},
        {"name": "search-code", "category": "DevTools", "label": "代码符号检索", "path": ring(420, 420, 260, 190) + " " + stroke((600, 600), (840, 840), 70) + " " + stroke((320, 420), (520, 420), 40)},
        {"name": "replace-code", "category": "DevTools", "label": "全局重构替换", "path": ring(420, 420, 260, 190) + " " + stroke((600, 600), (840, 840), 70) + " " + stroke((280, 420), (560, 420), 40) + " " + stroke((420, 280), (420, 560), 40)},
        {"name": "diff", "category": "DevTools", "label": "差异对比 (Diff)", "path": stroke((180, 320), (440, 320), 60) + " " + stroke((180, 500), (440, 500), 60) + " " + stroke((560, 320), (820, 320), 60) + " " + stroke((560, 680), (820, 680), 60) + " " + stroke((690, 190), (690, 450), 60)},
        {"name": "split-v", "category": "DevTools", "label": "垂直分栏编辑器", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((500, 180), (500, 820), 50)},
        {"name": "split-h", "category": "DevTools", "label": "水平分栏编辑器", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((140, 500), (860, 500), 50)},
        {"name": "layers", "category": "DevTools", "label": "架构层级与 AST 视图", "path": "M 500 160 L 860 320 L 500 480 L 140 320 Z " + stroke((140, 480), (500, 640), 40) + " " + stroke((860, 480), (500, 640), 40) + " " + stroke((140, 640), (500, 800), 40) + " " + stroke((860, 640), (500, 800), 40)},
        {"name": "cube", "category": "DevTools", "label": "构建单元 (Module)", "path": frame(200, 200, 600, 600, 60, 50) + " " + stroke((200, 200), (800, 800), 40) + " " + stroke((800, 200), (200, 800), 40)},
        {"name": "benchmark", "category": "DevTools", "label": "微基准吞吐量", "path": ring(500, 500, 400, 320) + " " + stroke((500, 500), (740, 360), 60) + " " + circle(500, 500, 80)},
        {"name": "speedometer", "category": "DevTools", "label": "超音速执行仪表", "path": arc(500, 560, 380, 140, 400, 60) + " " + stroke((500, 560), (720, 340), 60) + " " + circle(500, 560, 80)},
        {"name": "flamegraph", "category": "DevTools", "label": "火焰图性能分析", "path": rect(140, 680, 720, 120, 20) + " " + rect(220, 520, 560, 120, 20) + " " + rect(300, 360, 400, 120, 20) + " " + rect(420, 200, 160, 120, 20)},
        {"name": "bug", "category": "DevTools", "label": "Bug 缺陷调试", "path": ring(500, 520, 260, 180) + " " + circle(500, 260, 100) + " " + stroke((200, 420), (320, 480), 50) + " " + stroke((800, 420), (680, 480), 50) + " " + stroke((180, 620), (320, 580), 50) + " " + stroke((820, 620), (680, 580), 50)},
        {"name": "breakpoint", "category": "DevTools", "label": "断点", "path": circle(500, 500, 320)},
        {"name": "breakpoint-active", "category": "DevTools", "label": "命中活动断点", "path": circle(500, 500, 360) + " " + ring(500, 500, 460, 400)},
        {"name": "step-into", "category": "DevTools", "label": "单步步入 Step Into", "path": stroke((500, 180), (500, 680), 70) + " M 320 520 L 500 700 L 680 520 Z " + circle(500, 180, 45)},
        {"name": "step-over", "category": "DevTools", "label": "单步越过 Step Over", "path": arc(500, 680, 320, 180, 360, 70) + " M 640 540 L 760 680 L 880 540 Z"},
        {"name": "step-out", "category": "DevTools", "label": "单步跳出 Step Out", "path": stroke((500, 700), (500, 220), 70) + " M 320 380 L 500 200 L 680 380 Z " + circle(500, 700, 45)},
        {"name": "play", "category": "DevTools", "label": "开始运行/调试", "path": "M 280 180 L 820 500 L 280 820 Z"},
        {"name": "pause", "category": "DevTools", "label": "暂停执行", "path": rect(260, 180, 160, 640, 30) + " " + rect(580, 180, 160, 640, 30)},
        {"name": "stop", "category": "DevTools", "label": "终止进程", "path": rect(200, 200, 600, 600, 60)},
        {"name": "refresh", "category": "DevTools", "label": "热重载 / 重启调试", "path": arc(500, 500, 320, 45, 330, 70) + " M 640 240 L 820 340 L 820 160 Z"},
        {"name": "inspect", "category": "DevTools", "label": "运行时对象探查", "path": ring(420, 420, 260, 190) + " " + stroke((600, 600), (840, 840), 70) + " " + circle(420, 420, 70)},
        {"name": "variable", "category": "DevTools", "label": "局部变量表 (x, y)", "path": stroke((240, 320), (440, 680), 60) + " " + stroke((440, 320), (240, 680), 60) + " " + stroke((560, 320), (680, 520), 60) + " " + stroke((800, 320), (680, 520), 60) + " " + stroke((680, 520), (680, 740), 60)},
        {"name": "watch", "category": "DevTools", "label": "表达式监视", "path": ring(500, 500, 380, 300) + " " + stroke((500, 280), (500, 500), 60) + " " + stroke((500, 500), (680, 500), 60) + " " + stroke((360, 120), (640, 120), 50)},
        {"name": "callstack", "category": "DevTools", "label": "调用栈回溯", "path": rect(200, 200, 600, 140, 20) + " " + rect(200, 420, 600, 140, 20) + " " + rect(200, 640, 600, 140, 20)},
        {"name": "log-terminal", "category": "DevTools", "label": "日志控制台", "path": frame(140, 200, 720, 600, 60, 50) + " " + stroke((240, 360), (320, 440), 40) + " " + stroke((320, 440), (240, 520), 40) + " " + stroke((380, 520), (520, 520), 40) + " " + stroke((240, 640), (700, 640), 40)}
    ]

def get_git_devops_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "git-branch", "category": "Git & DevOps", "label": "Git 分支管理", "path": circle(320, 280, 90) + " " + circle(320, 720, 90) + " " + circle(680, 440, 90) + " " + stroke((320, 280), (320, 720), 60) + " " + arc(320, 440, 360, 270, 360, 60)},
        {"name": "git-commit", "category": "Git & DevOps", "label": "Git 提交节点", "path": ring(500, 500, 220, 140) + " " + stroke((120, 500), (280, 500), 60) + " " + stroke((720, 500), (880, 500), 60)},
        {"name": "git-merge", "category": "Git & DevOps", "label": "Git 分支合并", "path": circle(320, 280, 90) + " " + circle(320, 720, 90) + " " + circle(680, 560, 90) + " " + stroke((320, 280), (320, 720), 60) + " " + arc(680, 560, 360, 180, 270, 60)},
        {"name": "git-pull-request", "category": "Git & DevOps", "label": "代码合并请求 (PR)", "path": circle(320, 280, 90) + " " + circle(320, 720, 90) + " " + circle(680, 720, 90) + " " + stroke((320, 280), (320, 720), 60) + " " + stroke((680, 440), (680, 720), 60) + " " + arc(320, 440, 360, 270, 360, 60)},
        {"name": "git-compare", "category": "Git & DevOps", "label": "版本比对", "path": circle(320, 320, 90) + " " + circle(680, 680, 90) + " " + stroke((320, 410), (320, 680), 60) + " " + stroke((680, 320), (680, 590), 60) + " M 220 560 L 320 680 L 420 560 Z M 580 440 L 680 320 L 780 440 Z"},
        {"name": "git-fork", "category": "Git & DevOps", "label": "派生分支 (Fork)", "path": circle(500, 260, 90) + " " + circle(280, 740, 90) + " " + circle(720, 740, 90) + " " + stroke((500, 260), (500, 480), 60) + " " + stroke((500, 480), (280, 740), 60) + " " + stroke((500, 480), (720, 740), 60)},
        {"name": "git-tag", "category": "Git & DevOps", "label": "版本标签 Tag", "path": "M 200 480 L 480 200 L 800 200 L 800 520 L 520 800 Z " + circle(660, 340, 50)},
        {"name": "git-stash", "category": "Git & DevOps", "label": "暂存暂挂 Stash", "path": rect(180, 220, 640, 140, 20) + " " + rect(180, 430, 640, 140, 20) + " " + rect(180, 640, 640, 140, 20)},
        {"name": "git-cherry-pick", "category": "Git & DevOps", "label": "挑选提交 Cherry-pick", "path": circle(360, 680, 90) + " " + circle(640, 680, 90) + " " + stroke((360, 680), (500, 320), 50) + " " + stroke((640, 680), (500, 320), 50) + " " + circle(500, 320, 50)},
        {"name": "repo", "category": "Git & DevOps", "label": "代码仓库", "path": frame(180, 160, 640, 680, 60, 50) + " " + stroke((180, 340), (820, 340), 50) + " " + circle(340, 560, 50)},
        {"name": "repo-forked", "category": "Git & DevOps", "label": "派生仓库", "path": frame(180, 160, 640, 680, 60, 50) + " " + stroke((360, 460), (640, 460), 40) + " " + stroke((500, 360), (500, 560), 40)},
        {"name": "shield-check", "category": "Git & DevOps", "label": "CI 合规检验通过", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z " + stroke((340, 520), (460, 640), 60) + " " + stroke((460, 640), (660, 380), 60)},
        {"name": "badge-check", "category": "Git & DevOps", "label": "官方认证徽章", "path": ring(500, 500, 420, 340) + " " + stroke((340, 500), (460, 620), 60) + " " + stroke((460, 620), (660, 400), 60)},
        {"name": "license", "category": "Git & DevOps", "label": "开源许可证", "path": frame(180, 160, 640, 680, 60, 50) + " " + stroke((300, 320), (700, 320), 40) + " " + stroke((300, 460), (700, 460), 40) + " " + stroke((300, 600), (540, 600), 40)},
        {"name": "package", "category": "Git & DevOps", "label": "制品安装包", "path": frame(180, 220, 640, 560, 60, 50) + " " + stroke((180, 220), (820, 780), 40) + " " + stroke((820, 220), (180, 780), 40)},
        {"name": "package-open", "category": "Git & DevOps", "label": "解包与模块发布", "path": frame(200, 360, 600, 460, 40, 40) + " " + stroke((140, 240), (500, 440), 40) + " " + stroke((860, 240), (500, 440), 40)},
        {"name": "build-box", "category": "Git & DevOps", "label": "构建箱 (Artifact)", "path": frame(160, 200, 680, 600, 80, 60) + " " + rect(320, 360, 360, 280, 30)},
        {"name": "pipeline", "category": "Git & DevOps", "label": "CI/CD 流水线", "path": circle(220, 500, 80) + " " + circle(500, 500, 80) + " " + circle(780, 500, 80) + " " + stroke((300, 500), (420, 500), 50) + " " + stroke((580, 500), (700, 500), 50)},
        {"name": "container", "category": "Git & DevOps", "label": "Docker 容器镜像", "path": frame(140, 240, 720, 520, 60, 50) + " " + rect(240, 340, 120, 120, 20) + " " + rect(440, 340, 120, 120, 20) + " " + rect(640, 340, 120, 120, 20) + " " + rect(340, 520, 120, 120, 20) + " " + rect(540, 520, 120, 120, 20)},
        {"name": "rocket", "category": "Git & DevOps", "label": "一键发布上线", "path": "M 500 120 C 660 260 720 480 660 700 L 500 620 L 340 700 C 280 480 340 260 500 120 Z " + circle(500, 400, 60)},
        {"name": "target", "category": "Git & DevOps", "label": "构建目标 Target", "path": ring(500, 500, 400, 320) + " " + ring(500, 500, 220, 140) + " " + circle(500, 500, 50)},
        {"name": "milestone", "category": "Git & DevOps", "label": "开发里程碑", "path": stroke((200, 160), (200, 840), 60) + " M 200 220 L 780 380 L 200 540 Z"},
        {"name": "deploy", "category": "Git & DevOps", "label": "云原生部署", "path": "M 320 740 L 740 740 C 840 740 900 660 900 560 C 900 480 840 400 760 380 C 740 240 620 140 480 140 C 360 140 260 220 220 340 C 140 360 80 440 80 540 C 80 640 160 740 320 740 Z " + stroke((500, 660), (500, 400), 50) + " M 380 480 L 500 360 L 620 480 Z"},
        {"name": "webhook", "category": "Git & DevOps", "label": "Webhook 事件钩子", "path": circle(500, 260, 100) + " " + circle(300, 700, 90) + " " + circle(700, 700, 90) + " " + stroke((500, 260), (300, 700), 50) + " " + stroke((500, 260), (700, 700), 50)}
    ]

def get_network_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "globe", "category": "Network", "label": "全球互联网络", "path": ring(500, 500, 400, 320) + " " + stroke((100, 500), (900, 500), 60) + " " + arc(500, 500, 260, 90, 270, 60) + " " + arc(500, 500, 260, 270, 450, 60)},
        {"name": "server", "category": "Network", "label": "后端服务器集群", "path": frame(160, 180, 680, 200, 40, 45) + " " + frame(160, 420, 680, 200, 40, 45) + " " + frame(160, 660, 680, 200, 40, 45) + " " + circle(280, 280, 30) + " " + circle(280, 520, 30) + " " + circle(280, 760, 30)},
        {"name": "cloud", "category": "Network", "label": "云端服务", "path": "M 320 780 L 740 780 C 840 780 900 700 900 600 C 900 520 840 440 760 420 C 740 280 620 180 480 180 C 360 180 260 260 220 380 C 140 400 80 480 80 580 C 80 680 160 780 320 780 Z"},
        {"name": "cloud-upload", "category": "Network", "label": "云端上传", "path": "M 320 780 L 740 780 C 840 780 900 700 900 600 C 900 520 840 440 760 420 C 740 280 620 180 480 180 C 360 180 260 260 220 380 C 140 400 80 480 80 580 C 80 680 160 780 320 780 Z " + stroke((500, 680), (500, 440), 60) + " M 380 520 L 500 400 L 620 520 Z"},
        {"name": "cloud-download", "category": "Network", "label": "云端拉取下载", "path": "M 320 780 L 740 780 C 840 780 900 700 900 600 C 900 520 840 440 760 420 C 740 280 620 180 480 180 C 360 180 260 260 220 380 C 140 400 80 480 80 580 C 80 680 160 780 320 780 Z " + stroke((500, 420), (500, 680), 60) + " M 360 580 L 500 720 L 640 580 Z"},
        {"name": "cloud-sync", "category": "Network", "label": "云端同步", "path": "M 320 780 L 740 780 C 840 780 900 700 900 600 C 900 520 840 440 760 420 C 740 280 620 180 480 180 C 360 180 260 260 220 380 C 140 400 80 480 80 580 C 80 680 160 780 320 780 Z " + arc(500, 520, 120, 45, 315, 35) + " M 580 400 L 640 460 L 540 460 Z"},
        {"name": "api", "category": "Network", "label": "API 接口端点", "path": circle(260, 500, 100) + " " + circle(740, 320, 100) + " " + circle(740, 680, 100) + " " + stroke((360, 460), (640, 360), 60) + " " + stroke((360, 540), (640, 640), 60)},
        {"name": "wifi", "category": "Network", "label": "Wi-Fi 无线网络", "path": circle(500, 780, 60) + " " + arc(500, 780, 200, 225, 315, 50) + " " + arc(500, 780, 360, 225, 315, 50) + " " + arc(500, 780, 520, 225, 315, 50)},
        {"name": "wifi-off", "category": "Network", "label": "无线网络断开", "path": circle(500, 780, 60) + " " + arc(500, 780, 200, 225, 315, 50) + " " + arc(500, 780, 360, 225, 315, 50) + " " + stroke((140, 140), (860, 860), 60)},
        {"name": "bluetooth", "category": "Network", "label": "蓝牙近场通信", "path": stroke((300, 320), (700, 680), 60) + " " + stroke((700, 680), (500, 840), 60) + " " + stroke((500, 840), (500, 160), 60) + " " + stroke((500, 160), (700, 320), 60) + " " + stroke((700, 320), (300, 680), 60)},
        {"name": "socket", "category": "Network", "label": "网络套接字 (Socket)", "path": frame(160, 200, 680, 600, 80, 60) + " " + circle(340, 440, 50) + " " + circle(660, 440, 50) + " " + stroke((500, 560), (500, 680), 50)},
        {"name": "link", "category": "Network", "label": "网络超链接", "path": arc(380, 500, 180, 90, 270, 60) + " " + arc(620, 500, 180, 270, 450, 60) + " " + stroke((380, 380), (620, 380), 60) + " " + stroke((380, 620), (620, 620), 60)},
        {"name": "unlink", "category": "Network", "label": "断开超链接", "path": arc(380, 500, 180, 90, 270, 60) + " " + arc(620, 500, 180, 270, 450, 60) + " " + stroke((140, 140), (860, 860), 60)},
        {"name": "rss", "category": "Network", "label": "RSS 订阅流", "path": circle(240, 760, 80) + " " + arc(160, 840, 340, 270, 360, 60) + " " + arc(160, 840, 600, 270, 360, 60)},
        {"name": "signal", "category": "Network", "label": "通信信号量", "path": rect(160, 680, 100, 160, 20) + " " + rect(340, 520, 100, 320, 20) + " " + rect(520, 360, 100, 480, 20) + " " + rect(700, 200, 100, 640, 20)},
        {"name": "broadcast", "category": "Network", "label": "广播信道", "path": stroke((500, 360), (500, 840), 60) + " " + circle(500, 260, 100) + " " + arc(500, 260, 220, 180, 360, 50) + " " + arc(500, 260, 380, 180, 360, 50)},
        {"name": "router", "category": "Network", "label": "路由器网关", "path": frame(160, 480, 680, 320, 40, 50) + " " + stroke((280, 200), (280, 480), 50) + " " + stroke((720, 200), (720, 480), 50) + " " + circle(280, 640, 30) + " " + circle(400, 640, 30) + " " + circle(520, 640, 30) + " " + circle(640, 640, 30)},
        {"name": "shield-network", "category": "Network", "label": "网络安全防火墙", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z " + circle(500, 500, 140)},
        {"name": "http", "category": "Network", "label": "HTTP/HTTPS 协议", "path": frame(120, 240, 760, 520, 60, 50) + " " + stroke((240, 380), (240, 620), 50) + " " + stroke((340, 380), (340, 620), 50) + " " + stroke((240, 500), (340, 500), 50) + " " + stroke((440, 380), (600, 380), 50) + " " + stroke((520, 380), (520, 620), 50) + " " + stroke((700, 380), (700, 620), 50)},
        {"name": "websocket", "category": "Network", "label": "WebSocket 长连接", "path": stroke((300, 240), (700, 240), 60) + " M 620 140 L 760 240 L 620 340 Z " + stroke((700, 760), (300, 760), 60) + " M 380 660 L 240 760 L 380 860 Z " + circle(500, 500, 100)},
        {"name": "json", "category": "Network", "label": "JSON 数据格式", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((320, 340), (260, 420), 40) + " " + stroke((260, 420), (320, 500), 40) + " " + stroke((680, 340), (740, 420), 40) + " " + stroke((740, 420), (680, 500), 40) + " " + stroke((400, 620), (600, 620), 40)},
        {"name": "xml", "category": "Network", "label": "XML 节点标记", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((360, 360), (260, 500), 50) + " " + stroke((260, 500), (360, 640), 50) + " " + stroke((640, 360), (740, 500), 50) + " " + stroke((740, 500), (640, 640), 50) + " " + stroke((540, 340), (460, 660), 45)},
        {"name": "yaml", "category": "Network", "label": "YAML 配置文件", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((260, 360), (360, 500), 45) + " " + stroke((460, 360), (360, 500), 45) + " " + stroke((360, 500), (360, 640), 45) + " " + stroke((560, 360), (740, 360), 45) + " " + stroke((560, 500), (740, 500), 45) + " " + stroke((560, 640), (740, 640), 45)},
        {"name": "ip", "category": "Network", "label": "IP 地址定位", "path": ring(500, 500, 400, 320) + " " + circle(500, 500, 120)},
        {"name": "domain", "category": "Network", "label": "DNS 域名系统", "path": ring(500, 500, 400, 320) + " " + stroke((100, 500), (900, 500), 50) + " " + stroke((500, 100), (500, 900), 50)},
        {"name": "proxy", "category": "Network", "label": "反向代理网关", "path": frame(160, 240, 680, 520, 60, 50) + " " + stroke((300, 400), (700, 400), 50) + " M 600 320 L 720 400 L 600 480 Z " + stroke((700, 600), (300, 600), 50) + " M 400 520 L 280 600 L 400 680 Z"},
        {"name": "firewall", "category": "Network", "label": "网络防火墙", "path": frame(160, 200, 680, 600, 40, 50) + " " + stroke((160, 400), (840, 400), 40) + " " + stroke((160, 600), (840, 600), 40) + " " + stroke((380, 200), (380, 400), 40) + " " + stroke((620, 200), (620, 400), 40) + " " + stroke((500, 400), (500, 600), 40) + " " + stroke((380, 600), (380, 800), 40) + " " + stroke((620, 600), (620, 800), 40)},
        {"name": "ssl-tls", "category": "Network", "label": "TLS/SSL 加密传输", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z " + ring(500, 460, 140, 80) + " " + rect(400, 560, 200, 160, 20)}
    ]

def get_database_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "database", "category": "Database & Storage", "label": "数据库集群", "path": arc(500, 260, 320, 0, 180, 40) + " " + arc(500, 260, 320, 180, 360, 40) + " " + arc(500, 500, 320, 0, 180, 40) + " " + arc(500, 740, 320, 0, 180, 40) + " " + stroke((180, 260), (180, 740), 40) + " " + stroke((820, 260), (820, 740), 40)},
        {"name": "database-table", "category": "Database & Storage", "label": "关系型数据表", "path": frame(140, 200, 720, 600, 60, 50) + " " + stroke((140, 380), (860, 380), 50) + " " + stroke((380, 200), (380, 800), 50)},
        {"name": "database-query", "category": "Database & Storage", "label": "SQL 查询检索", "path": frame(140, 200, 720, 600, 60, 50) + " " + ring(600, 600, 160, 100) + " " + stroke((720, 720), (860, 860), 60)},
        {"name": "database-lock", "category": "Database & Storage", "label": "行级与表级悲观锁", "path": frame(140, 200, 720, 600, 60, 50) + " " + rect(520, 520, 240, 200, 30) + " " + arc(640, 440, 80, 180, 360, 30)},
        {"name": "database-backup", "category": "Database & Storage", "label": "数据灾备与归档", "path": frame(140, 200, 720, 600, 60, 50) + " " + arc(500, 560, 140, 0, 270, 40) + " M 640 460 L 680 560 L 580 560 Z"},
        {"name": "table", "category": "Database & Storage", "label": "数据表格视图", "path": frame(140, 180, 720, 640, 60, 50) + " " + stroke((140, 360), (860, 360), 40) + " " + stroke((140, 540), (860, 540), 40) + " " + stroke((380, 180), (380, 820), 40) + " " + stroke((620, 180), (620, 820), 40)},
        {"name": "columns", "category": "Database & Storage", "label": "数据列字段", "path": rect(160, 200, 300, 600, 30) + " " + rect(540, 200, 300, 600, 30)},
        {"name": "rows", "category": "Database & Storage", "label": "数据行记录", "path": rect(160, 200, 680, 160, 30) + " " + rect(160, 420, 680, 160, 30) + " " + rect(160, 640, 680, 160, 30)},
        {"name": "server-rack", "category": "Database & Storage", "label": "机架式服务器", "path": frame(180, 160, 640, 680, 40, 45) + " " + stroke((180, 380), (820, 380), 40) + " " + stroke((180, 600), (820, 600), 40) + " " + circle(280, 270, 25) + " " + circle(280, 490, 25) + " " + circle(280, 710, 25)},
        {"name": "hard-drive", "category": "Database & Storage", "label": "机械硬盘 (HDD)", "path": frame(160, 260, 680, 480, 60, 50) + " " + circle(720, 500, 35) + " " + stroke((240, 500), (560, 500), 40)},
        {"name": "ssd", "category": "Database & Storage", "label": "固态硬盘 (NVMe SSD)", "path": frame(180, 220, 640, 560, 60, 50) + " " + rect(260, 300, 140, 180, 20) + " " + rect(440, 300, 140, 180, 20) + " " + stroke((260, 620), (740, 620), 40)},
        {"name": "usb", "category": "Database & Storage", "label": "USB 闪存盘", "path": rect(340, 360, 320, 480, 40) + " " + frame(400, 160, 200, 200, 20, 30) + " " + rect(440, 220, 40, 60, 5) + " " + rect(520, 220, 40, 60, 5)},
        {"name": "sd-card", "category": "Database & Storage", "label": "SD 存储卡", "path": frame(220, 180, 560, 640, 60, 50) + " " + rect(300, 240, 60, 120, 10) + " " + rect(420, 240, 60, 120, 10) + " " + rect(540, 240, 60, 120, 10) + " " + rect(660, 240, 60, 120, 10)},
        {"name": "floppy", "category": "Database & Storage", "label": "软盘存储镜像", "path": frame(180, 180, 640, 640, 60, 50) + " " + rect(320, 180, 360, 240, 20) + " " + rect(280, 540, 440, 280, 20)}
    ]

def get_security_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "security", "category": "Security & Auth", "label": "综合安全防护", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z " + stroke((340, 500), (460, 620), 60) + " " + stroke((460, 620), (660, 400), 60)},
        {"name": "lock", "category": "Security & Auth", "label": "加锁保护", "path": arc(500, 360, 160, 180, 360, 60) + " " + stroke((340, 360), (340, 480), 60) + " " + stroke((660, 360), (660, 480), 60) + " " + frame(220, 480, 560, 400, 60, 50) + " " + circle(500, 640, 45) + " " + stroke((500, 640), (500, 760), 40)},
        {"name": "unlock", "category": "Security & Auth", "label": "解锁权限", "path": arc(500, 340, 160, 180, 360, 60) + " " + stroke((340, 340), (340, 480), 60) + " " + frame(220, 480, 560, 400, 60, 50) + " " + circle(500, 640, 45)},
        {"name": "key", "category": "Security & Auth", "label": "公钥与密钥 Key", "path": ring(360, 500, 180, 100) + " " + stroke((540, 500), (840, 500), 60) + " " + stroke((720, 500), (720, 640), 50) + " " + stroke((840, 500), (840, 640), 50)},
        {"name": "keyhole", "category": "Security & Auth", "label": "钥匙孔", "path": ring(500, 500, 400, 320) + " " + circle(500, 420, 70) + " M 460 460 L 540 460 L 580 680 L 420 680 Z"},
        {"name": "shield", "category": "Security & Auth", "label": "防护盾牌", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z M 500 200 L 240 290 L 240 540 C 240 700 360 800 500 840 C 640 800 760 700 760 540 L 760 290 Z"},
        {"name": "shield-alert", "category": "Security & Auth", "label": "安全漏洞告警", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z " + stroke((500, 320), (500, 560), 60) + " " + circle(500, 700, 40)},
        {"name": "fingerprint", "category": "Security & Auth", "label": "生物指纹识别", "path": arc(500, 500, 300, 180, 360, 40) + " " + arc(500, 500, 220, 180, 360, 40) + " " + arc(500, 500, 140, 180, 360, 40) + " " + arc(500, 500, 60, 180, 360, 30) + " " + stroke((500, 500), (500, 800), 40) + " " + stroke((420, 500), (420, 760), 40) + " " + stroke((580, 500), (580, 760), 40)},
        {"name": "scan", "category": "Security & Auth", "label": "安全审计扫描", "path": stroke((160, 320), (160, 180), 50) + " " + stroke((160, 180), (300, 180), 50) + " " + stroke((700, 180), (840, 180), 50) + " " + stroke((840, 180), (840, 320), 50) + " " + stroke((160, 680), (160, 820), 50) + " " + stroke((160, 820), (300, 820), 50) + " " + stroke((700, 820), (840, 820), 50) + " " + stroke((840, 820), (840, 680), 50) + " " + stroke((140, 500), (860, 500), 50)},
        {"name": "face-id", "category": "Security & Auth", "label": "人脸识别验证", "path": stroke((160, 320), (160, 180), 50) + " " + stroke((160, 180), (300, 180), 50) + " " + stroke((700, 180), (840, 180), 50) + " " + stroke((840, 180), (840, 320), 50) + " " + stroke((160, 680), (160, 820), 50) + " " + stroke((160, 820), (300, 820), 50) + " " + stroke((700, 820), (840, 820), 50) + " " + stroke((840, 820), (840, 680), 50) + " " + circle(360, 420, 40) + " " + circle(640, 420, 40) + " " + stroke((500, 460), (500, 560), 40) + " " + arc(500, 600, 120, 0, 180, 40)},
        {"name": "id-card", "category": "Security & Auth", "label": "数字身份凭证", "path": frame(140, 200, 720, 600, 60, 50) + " " + circle(340, 440, 80) + " " + arc(340, 640, 100, 180, 360, 40) + " " + stroke((520, 360), (760, 360), 40) + " " + stroke((520, 480), (760, 480), 40) + " " + stroke((520, 600), (680, 600), 40)},
        {"name": "certificate", "category": "Security & Auth", "label": "SSL/X.509 证书", "path": frame(160, 160, 680, 680, 60, 50) + " " + stroke((260, 280), (740, 280), 40) + " " + stroke((260, 400), (540, 400), 40) + " " + ring(640, 620, 100, 50)},
        {"name": "password", "category": "Security & Auth", "label": "口令与哈希密码", "path": frame(140, 320, 720, 360, 60, 50) + " " + circle(300, 500, 40) + " " + circle(440, 500, 40) + " " + circle(580, 500, 40) + " " + circle(720, 500, 40)},
        {"name": "mask", "category": "Security & Auth", "label": "数据脱敏", "path": "M 200 360 C 340 300 440 380 500 380 C 560 380 660 300 800 360 C 800 580 680 700 500 700 C 320 700 200 580 200 360 Z " + circle(360, 480, 40) + " " + circle(640, 480, 40)},
        {"name": "incognito", "category": "Security & Auth", "label": "隐私无痕模式", "path": "M 200 380 L 800 380 L 700 240 L 300 240 Z " + stroke((140, 400), (860, 400), 40) + " " + ring(350, 580, 120, 60) + " " + ring(650, 580, 120, 60) + " " + stroke((470, 580), (530, 580), 40)},
        {"name": "vpn", "category": "Security & Auth", "label": "VPN 加密网络", "path": ring(500, 500, 400, 320) + " " + frame(360, 400, 280, 240, 40, 30) + " " + stroke((500, 280), (500, 400), 30)},
        {"name": "tamper-proof", "category": "Security & Auth", "label": "防篡改验签", "path": "M 500 120 L 840 240 L 840 540 C 840 740 680 860 500 920 C 320 860 160 740 160 540 L 160 240 Z " + stroke((340, 520), (460, 640), 60) + " " + stroke((460, 640), (660, 380), 60)}
    ]

def get_files_media_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "file", "category": "Files & Media", "label": "普通文件", "path": frame(200, 140, 600, 720, 60, 50)},
        {"name": "file-code", "category": "Files & Media", "label": "源码文件 (.xu)", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((380, 440), (300, 520), 45) + " " + stroke((300, 520), (380, 600), 45) + " " + stroke((620, 440), (700, 520), 45) + " " + stroke((700, 520), (620, 600), 45) + " " + stroke((530, 400), (470, 640), 40)},
        {"name": "file-binary", "category": "Files & Media", "label": "原生可执行机器码", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((360, 420), (360, 620), 50) + " " + ring(620, 520, 100, 50)},
        {"name": "file-text", "category": "Files & Media", "label": "纯文本文件 (.txt)", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((320, 380), (680, 380), 40) + " " + stroke((320, 500), (680, 500), 40) + " " + stroke((320, 620), (520, 620), 40)},
        {"name": "file-pdf", "category": "Files & Media", "label": "PDF 版式文档", "path": frame(200, 140, 600, 720, 60, 50) + " " + rect(300, 460, 400, 200, 30)},
        {"name": "file-archive", "category": "Files & Media", "label": "压缩包 (.zip)", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((480, 280), (520, 280), 35) + " " + stroke((480, 380), (520, 380), 35) + " " + stroke((480, 480), (520, 480), 35) + " " + rect(460, 580, 80, 120, 15)},
        {"name": "file-audio", "category": "Files & Media", "label": "音频工程文件", "path": frame(200, 140, 600, 720, 60, 50) + " " + circle(420, 600, 50) + " " + stroke((470, 600), (470, 400), 40) + " " + stroke((470, 400), (580, 360), 40)},
        {"name": "file-video", "category": "Files & Media", "label": "视频流媒体文件", "path": frame(200, 140, 600, 720, 60, 50) + " M 420 420 L 620 520 L 420 620 Z"},
        {"name": "file-image", "category": "Files & Media", "label": "图像文件 (.svg/.png)", "path": frame(200, 140, 600, 720, 60, 50) + " " + circle(380, 420, 50) + " M 300 680 L 460 520 L 580 640 L 680 540 L 720 580 L 720 680 Z"},
        {"name": "file-check", "category": "Files & Media", "label": "校验通过文件", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((360, 520), (460, 620), 50) + " " + stroke((460, 620), (640, 420), 50)},
        {"name": "file-plus", "category": "Files & Media", "label": "新建文件", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((380, 520), (620, 520), 50) + " " + stroke((500, 400), (500, 640), 50)},
        {"name": "file-minus", "category": "Files & Media", "label": "移除文件", "path": frame(200, 140, 600, 720, 60, 50) + " " + stroke((380, 520), (620, 520), 50)},
        {"name": "file-search", "category": "Files & Media", "label": "文件全文搜索", "path": frame(200, 140, 600, 720, 60, 50) + " " + ring(480, 520, 120, 80) + " " + stroke((580, 620), (680, 720), 40)},
        {"name": "folder", "category": "Files & Media", "label": "文件目录文件夹", "path": "M 160 220 L 400 220 L 480 320 L 840 320 C 880 320 900 340 900 380 L 900 760 C 900 800 880 820 840 820 L 160 820 C 120 820 100 800 100 760 L 100 280 C 100 240 120 220 160 220 Z"},
        {"name": "folder-open", "category": "Files & Media", "label": "展开文件夹", "path": frame(140, 220, 720, 580, 60, 45) + " " + stroke((140, 420), (860, 420), 45)},
        {"name": "folder-plus", "category": "Files & Media", "label": "新建子目录", "path": frame(140, 220, 720, 580, 60, 45) + " " + stroke((400, 520), (600, 520), 45) + " " + stroke((500, 420), (500, 620), 45)},
        {"name": "folder-minus", "category": "Files & Media", "label": "删除目录", "path": frame(140, 220, 720, 580, 60, 45) + " " + stroke((400, 520), (600, 520), 45)},
        {"name": "folder-check", "category": "Files & Media", "label": "目录合规归档", "path": frame(140, 220, 720, 580, 60, 45) + " " + stroke((380, 520), (480, 620), 45) + " " + stroke((480, 620), (640, 440), 45)},
        {"name": "folder-tree", "category": "Files & Media", "label": "目录层级树", "path": rect(140, 160, 280, 160, 20) + " " + rect(500, 420, 280, 160, 20) + " " + rect(500, 680, 280, 160, 20) + " " + stroke((280, 320), (280, 760), 40) + " " + stroke((280, 500), (500, 500), 40) + " " + stroke((280, 760), (500, 760), 40)},
        {"name": "image", "category": "Files & Media", "label": "图片画廊视图", "path": frame(140, 180, 720, 640, 60, 50) + " " + circle(340, 380, 60) + " M 220 720 L 440 480 L 580 620 L 680 520 L 780 620 L 780 720 Z"},
        {"name": "video", "category": "Files & Media", "label": "视频播放器", "path": frame(140, 240, 540, 520, 60, 50) + " M 680 420 L 860 300 L 860 700 L 680 580 Z"},
        {"name": "music", "category": "Files & Media", "label": "音乐音轨", "path": circle(360, 680, 100) + " " + circle(700, 580, 100) + " " + stroke((440, 680), (440, 240), 50) + " " + stroke((780, 580), (780, 140), 50) + " " + stroke((440, 240), (780, 140), 60)},
        {"name": "headphones", "category": "Files & Media", "label": "开发者耳机", "path": arc(500, 500, 320, 180, 360, 60) + " " + rect(140, 480, 120, 260, 30) + " " + rect(740, 480, 120, 260, 30)},
        {"name": "mic", "category": "Files & Media", "label": "麦克风录音", "path": rect(380, 160, 240, 440, 80) + " " + arc(500, 460, 260, 0, 180, 50) + " " + stroke((500, 720), (500, 860), 50) + " " + stroke((340, 860), (660, 860), 50)},
        {"name": "mic-off", "category": "Files & Media", "label": "麦克风静音", "path": rect(380, 160, 240, 440, 80) + " " + arc(500, 460, 260, 0, 180, 50) + " " + stroke((140, 140), (860, 860), 60)},
        {"name": "camera", "category": "Files & Media", "label": "高清摄像头", "path": frame(140, 260, 720, 540, 60, 50) + " " + ring(500, 530, 160, 100) + " M 340 260 L 400 160 L 600 160 L 660 260 Z"},
        {"name": "volume-high", "category": "Files & Media", "label": "高音量输出", "path": "M 200 380 L 360 380 L 520 240 L 520 760 L 360 620 L 200 620 Z " + arc(360, 500, 280, 315, 405, 50) + " " + arc(360, 500, 440, 315, 405, 50)},
        {"name": "volume-low", "category": "Files & Media", "label": "低音量输出", "path": "M 200 380 L 360 380 L 520 240 L 520 760 L 360 620 L 200 620 Z " + arc(360, 500, 280, 315, 405, 50)},
        {"name": "volume-mute", "category": "Files & Media", "label": "静音模式", "path": "M 200 380 L 360 380 L 520 240 L 520 760 L 360 620 L 200 620 Z " + stroke((660, 400), (840, 600), 50) + " " + stroke((840, 400), (660, 600), 50)},
        {"name": "play-circle", "category": "Files & Media", "label": "播放圆环", "path": ring(500, 500, 420, 340) + " M 440 360 L 660 500 L 440 640 Z"},
        {"name": "pause-circle", "category": "Files & Media", "label": "暂停圆环", "path": ring(500, 500, 420, 340) + " " + rect(380, 340, 80, 320, 15) + " " + rect(540, 340, 80, 320, 15)},
        {"name": "film", "category": "Files & Media", "label": "胶片电影帧", "path": frame(140, 200, 720, 600, 60, 50) + " " + stroke((140, 360), (860, 360), 40) + " " + stroke((140, 640), (860, 640), 40) + " " + stroke((300, 200), (300, 360), 40) + " " + stroke((500, 200), (500, 360), 40) + " " + stroke((700, 200), (700, 360), 40) + " " + stroke((300, 640), (300, 800), 40) + " " + stroke((500, 640), (500, 800), 40) + " " + stroke((700, 640), (700, 800), 40)},
        {"name": "sliders-v", "category": "Files & Media", "label": "调音台滑块", "path": stroke((300, 160), (300, 840), 40) + " " + stroke((500, 160), (500, 840), 40) + " " + stroke((700, 160), (700, 840), 40) + " " + rect(220, 340, 160, 100, 20) + " " + rect(420, 560, 160, 100, 20) + " " + rect(620, 240, 160, 100, 20)},
        {"name": "equalizer", "category": "Files & Media", "label": "频谱均衡器", "path": stroke((200, 380), (200, 620), 50) + " " + stroke((350, 240), (350, 760), 50) + " " + stroke((500, 140), (500, 860), 50) + " " + stroke((650, 300), (650, 700), 50) + " " + stroke((800, 420), (800, 580), 50)},
        {"name": "crop", "category": "Files & Media", "label": "图像裁剪", "path": stroke((160, 340), (840, 340), 50) + " " + stroke((340, 160), (340, 840), 50) + " " + stroke((340, 660), (840, 660), 50) + " " + stroke((660, 340), (660, 840), 50)},
        {"name": "expand", "category": "Files & Media", "label": "全屏展开", "path": stroke((160, 360), (160, 160), 60) + " " + stroke((160, 160), (360, 160), 60) + " " + stroke((840, 360), (840, 160), 60) + " " + stroke((840, 160), (640, 160), 60) + " " + stroke((160, 640), (160, 840), 60) + " " + stroke((160, 840), (360, 840), 60) + " " + stroke((840, 640), (840, 840), 60) + " " + stroke((840, 840), (640, 840), 60)},
        {"name": "compress-arrows", "category": "Files & Media", "label": "退出全屏折叠", "path": stroke((360, 160), (360, 360), 60) + " " + stroke((360, 360), (160, 360), 60) + " " + stroke((640, 160), (640, 360), 60) + " " + stroke((640, 360), (840, 360), 60) + " " + stroke((360, 840), (360, 640), 60) + " " + stroke((360, 640), (160, 640), 60) + " " + stroke((640, 840), (640, 640), 60) + " " + stroke((640, 640), (840, 640), 60)},
        {"name": "disc", "category": "Files & Media", "label": "光盘介质", "path": ring(500, 500, 400, 160) + " " + circle(500, 500, 60)}
    ]

def get_hardware_devices_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "monitor", "category": "Hardware & Devices", "label": "桌面高清显示器", "path": frame(120, 160, 760, 500, 60, 50) + " " + stroke((500, 660), (500, 840), 60) + " " + stroke((340, 840), (660, 840), 60)},
        {"name": "laptop", "category": "Hardware & Devices", "label": "便携笔记本电脑", "path": frame(200, 200, 600, 420, 40, 40) + " M 120 720 L 880 720 L 820 620 L 180 620 Z " + stroke((420, 650), (580, 650), 30)},
        {"name": "smartphone", "category": "Hardware & Devices", "label": "智能手机", "path": frame(260, 140, 480, 720, 80, 50) + " " + stroke((440, 220), (560, 220), 40) + " " + circle(500, 760, 30)},
        {"name": "tablet", "category": "Hardware & Devices", "label": "平板电脑", "path": frame(200, 140, 600, 720, 60, 50) + " " + circle(500, 780, 30)},
        {"name": "smartwatch", "category": "Hardware & Devices", "label": "智能穿戴手表", "path": frame(280, 280, 440, 440, 80, 50) + " " + rect(380, 140, 240, 140, 20) + " " + rect(380, 720, 240, 140, 20)},
        {"name": "keyboard", "category": "Hardware & Devices", "label": "机械键盘", "path": frame(140, 280, 720, 440, 60, 50) + " " + rect(220, 360, 80, 80, 15) + " " + rect(360, 360, 80, 80, 15) + " " + rect(500, 360, 80, 80, 15) + " " + rect(640, 360, 80, 80, 15) + " " + rect(300, 500, 340, 80, 15)},
        {"name": "mouse", "category": "Hardware & Devices", "label": "光电鼠标", "path": frame(280, 200, 440, 600, 220, 50) + " " + stroke((500, 200), (500, 480), 50)},
        {"name": "printer", "category": "Hardware & Devices", "label": "办公打印机", "path": frame(160, 340, 680, 360, 60, 50) + " " + frame(280, 180, 440, 160, 20, 40) + " " + rect(280, 580, 440, 220, 20)},
        {"name": "scanner", "category": "Hardware & Devices", "label": "高精扫描仪", "path": frame(160, 300, 680, 420, 60, 50) + " " + stroke((240, 440), (760, 440), 40) + " " + stroke((160, 300), (440, 160), 40)},
        {"name": "chip", "category": "Hardware & Devices", "label": "SoC 芯片架构", "path": frame(260, 260, 480, 480, 60, 50) + " " + rect(380, 380, 240, 240, 30) + " " + stroke((360, 140), (360, 260), 40) + " " + stroke((500, 140), (500, 260), 40) + " " + stroke((640, 140), (640, 260), 40) + " " + stroke((360, 740), (360, 860), 40) + " " + stroke((500, 740), (500, 860), 40) + " " + stroke((640, 740), (640, 860), 40)},
        {"name": "motherboard", "category": "Hardware & Devices", "label": "硬件主板总线", "path": frame(160, 160, 680, 680, 60, 50) + " " + rect(260, 260, 200, 200, 20) + " " + stroke((520, 260), (740, 260), 40) + " " + stroke((520, 360), (740, 360), 40) + " " + stroke((260, 560), (740, 560), 40)},
        {"name": "gpu", "category": "Hardware & Devices", "label": "GPU 显卡加速", "path": frame(140, 260, 720, 480, 60, 50) + " " + ring(360, 500, 140, 80) + " " + ring(640, 500, 140, 80) + " " + stroke((200, 740), (800, 740), 40)},
        {"name": "fan", "category": "Hardware & Devices", "label": "散热风扇", "path": ring(500, 500, 400, 340) + " " + circle(500, 500, 80) + " M 500 420 C 500 240 640 240 640 380 Z M 580 500 C 760 500 760 640 620 640 Z M 500 580 C 500 760 360 760 360 620 Z M 420 500 C 240 500 240 360 380 360 Z"},
        {"name": "sensor", "category": "Hardware & Devices", "label": "物理传感器", "path": ring(500, 500, 400, 320) + " " + ring(500, 500, 240, 160) + " " + circle(500, 500, 60)},
        {"name": "battery", "category": "Hardware & Devices", "label": "动力电池", "path": frame(180, 300, 640, 400, 60, 50) + " " + rect(820, 420, 60, 160, 10) + " " + rect(260, 380, 440, 240, 20)},
        {"name": "battery-charging", "category": "Hardware & Devices", "label": "电池快充", "path": frame(180, 300, 640, 400, 60, 50) + " " + rect(820, 420, 60, 160, 10) + " M 540 360 L 440 520 L 520 520 L 460 640 L 580 480 L 500 480 Z"},
        {"name": "battery-low", "category": "Hardware & Devices", "label": "低电量警报", "path": frame(180, 300, 640, 400, 60, 50) + " " + rect(820, 420, 60, 160, 10) + " " + rect(260, 380, 120, 240, 20)},
        {"name": "plug", "category": "Hardware & Devices", "label": "电源插头", "path": rect(260, 380, 480, 360, 60) + " " + stroke((380, 180), (380, 380), 50) + " " + stroke((620, 180), (620, 380), 50) + " " + stroke((500, 740), (500, 880), 50)},
        {"name": "power", "category": "Hardware & Devices", "label": "电源开关键", "path": arc(500, 500, 300, 130, 410, 60) + " " + stroke((500, 140), (500, 460), 60)},
        {"name": "zap", "category": "Hardware & Devices", "label": "电能强劲脉冲", "path": "M 560 100 L 220 540 L 500 540 L 440 900 L 780 460 L 500 460 Z"},
        {"name": "gauge", "category": "Hardware & Devices", "label": "压力仪表盘", "path": ring(500, 500, 400, 320) + " " + stroke((500, 500), (680, 320), 50) + " " + circle(500, 500, 70)}
    ]

def get_ui_charts_math_icons(helpers):
    stroke = helpers['stroke']
    circle = helpers['circle']
    ring = helpers['ring']
    rect = helpers['rect']
    frame = helpers['frame']
    arc = helpers['arc']

    return [
        {"name": "sun", "category": "UI & Math", "label": "白天明亮模式", "path": ring(500, 500, 200, 140) + " " + stroke((500, 120), (500, 220), 50) + " " + stroke((500, 780), (500, 880), 50) + " " + stroke((120, 500), (220, 500), 50) + " " + stroke((780, 500), (880, 500), 50) + " " + stroke((230, 230), (300, 300), 50) + " " + stroke((700, 700), (770, 770), 50) + " " + stroke((770, 230), (700, 300), 50) + " " + stroke((300, 700), (230, 770), 50)},
        {"name": "moon", "category": "UI & Math", "label": "曜石暗黑模式", "path": "M 520 180 C 340 240 220 400 220 580 C 220 780 380 940 580 940 C 760 940 920 820 980 640 C 880 700 740 700 620 620 C 500 500 500 320 560 180 Z"},
        {"name": "palette", "category": "UI & Math", "label": "调色板", "path": "M 500 160 C 280 160 160 280 160 500 C 160 720 280 840 500 840 C 560 840 600 800 600 740 C 600 700 580 680 580 640 C 580 580 620 540 680 540 L 740 540 C 800 540 840 500 840 440 C 840 280 720 160 500 160 Z " + circle(320, 360, 40) + " " + circle(480, 300, 40) + " " + circle(640, 360, 40)},
        {"name": "contrast", "category": "UI & Math", "label": "对比度调节", "path": ring(500, 500, 400, 320) + " M 500 180 L 500 820 C 680 820 820 680 820 500 C 820 320 680 180 500 180 Z"},
        {"name": "eye", "category": "UI & Math", "label": "查看可见", "path": "M 140 500 C 260 280 740 280 860 500 C 740 720 260 720 140 500 Z " + ring(500, 500, 160, 100)},
        {"name": "eye-off", "category": "UI & Math", "label": "隐藏掩码", "path": "M 140 500 C 260 280 740 280 860 500 C 740 720 260 720 140 500 Z " + stroke((140, 140), (860, 860), 60)},
        {"name": "sparkles", "category": "UI & Math", "label": "AI 智能高光", "path": "M 480 140 C 480 320 640 460 840 460 C 640 460 480 600 480 780 C 480 600 320 460 120 460 C 320 460 480 320 480 140 Z " + circle(760, 240, 40)},
        {"name": "star", "category": "UI & Math", "label": "收藏星标", "path": "M 500 140 L 610 370 L 860 400 L 680 580 L 720 830 L 500 710 L 280 830 L 320 580 L 140 400 L 390 370 Z"},
        {"name": "star-half", "category": "UI & Math", "label": "半星评级", "path": "M 500 140 L 500 710 L 280 830 L 320 580 L 140 400 L 390 370 Z"},
        {"name": "heart", "category": "UI & Math", "label": "赞赏喜爱", "path": "M 500 820 C 200 620 140 460 140 340 C 140 200 240 140 360 140 C 440 140 500 200 500 200 C 500 200 560 140 640 140 C 760 140 860 200 860 340 C 860 460 800 620 500 820 Z"},
        {"name": "award", "category": "UI & Math", "label": "勋章荣誉", "path": ring(500, 360, 220, 140) + " M 380 540 L 300 840 L 500 740 L 700 840 L 620 540 Z"},
        {"name": "trophy", "category": "UI & Math", "label": "冠军奖杯", "path": "M 280 160 L 720 160 L 720 440 C 720 560 620 640 500 640 C 380 640 280 560 280 440 Z " + stroke((500, 640), (500, 780), 60) + " " + stroke((340, 780), (660, 780), 60) + " " + arc(280, 340, 120, 90, 270, 40) + " " + arc(720, 340, 120, 270, 450, 40)},
        {"name": "crown", "category": "UI & Math", "label": "至尊皇冠", "path": "M 160 360 L 260 740 L 740 740 L 840 360 L 640 520 L 500 260 L 360 520 Z"},
        {"name": "flag", "category": "UI & Math", "label": "标记旗帜", "path": stroke((240, 140), (240, 860), 60) + " M 240 200 L 760 340 L 240 480 Z"},
        {"name": "bookmark", "category": "UI & Math", "label": "书签标记", "path": "M 260 160 L 740 160 L 740 840 L 500 660 L 260 840 Z"},
        {"name": "home", "category": "UI & Math", "label": "门户首页", "path": "M 160 480 L 500 180 L 840 480 L 840 840 L 580 840 L 580 580 L 420 580 L 420 840 L 160 840 Z"},
        {"name": "menu", "category": "UI & Math", "label": "汉堡导航菜单", "path": stroke((180, 280), (820, 280), 60) + " " + stroke((180, 500), (820, 500), 60) + " " + stroke((180, 720), (820, 720), 60)},
        {"name": "menu-alt", "category": "UI & Math", "label": "偏置导航菜单", "path": stroke((180, 280), (820, 280), 60) + " " + stroke((180, 500), (600, 500), 60) + " " + stroke((180, 720), (720, 720), 60)},
        {"name": "more-h", "category": "UI & Math", "label": "水平更多操作", "path": circle(260, 500, 60) + " " + circle(500, 500, 60) + " " + circle(740, 500, 60)},
        {"name": "more-v", "category": "UI & Math", "label": "垂直更多操作", "path": circle(500, 260, 60) + " " + circle(500, 500, 60) + " " + circle(500, 740, 60)},
        {"name": "grid", "category": "UI & Math", "label": "网格矩阵视图", "path": rect(180, 180, 280, 280, 40) + " " + rect(540, 180, 280, 280, 40) + " " + rect(180, 540, 280, 280, 40) + " " + rect(540, 540, 280, 280, 40)},
        {"name": "list", "category": "UI & Math", "label": "列表清单视图", "path": stroke((380, 280), (820, 280), 50) + " " + stroke((380, 500), (820, 500), 50) + " " + stroke((380, 720), (820, 720), 50) + " " + circle(220, 280, 40) + " " + circle(220, 500, 40) + " " + circle(220, 720, 40)},
        {"name": "list-ordered", "category": "UI & Math", "label": "编号顺序列表", "path": stroke((420, 280), (820, 280), 50) + " " + stroke((420, 500), (820, 500), 50) + " " + stroke((420, 720), (820, 720), 50) + " " + stroke((240, 220), (240, 340), 40) + " " + stroke((180, 460), (280, 460), 40) + " " + stroke((180, 680), (280, 680), 40)},
        {"name": "tree", "category": "UI & Math", "label": "树状层级结构", "path": rect(180, 160, 200, 160, 20) + " " + rect(540, 420, 200, 160, 20) + " " + rect(540, 680, 200, 160, 20) + " " + stroke((280, 320), (280, 760), 40) + " " + stroke((280, 500), (540, 500), 40) + " " + stroke((280, 760), (540, 760), 40)},
        {"name": "chevron-up", "category": "UI & Math", "label": "向上折叠", "path": stroke((200, 620), (500, 340), 70) + " " + stroke((500, 340), (800, 620), 70)},
        {"name": "chevron-down", "category": "UI & Math", "label": "向下展开", "path": stroke((200, 380), (500, 660), 70) + " " + stroke((500, 660), (800, 380), 70)},
        {"name": "chevron-left", "category": "UI & Math", "label": "向左翻页", "path": stroke((620, 200), (340, 500), 70) + " " + stroke((340, 500), (620, 800), 70)},
        {"name": "chevron-right", "category": "UI & Math", "label": "向右翻页", "path": stroke((380, 200), (660, 500), 70) + " " + stroke((660, 500), (380, 800), 70)},
        {"name": "chevrons-up", "category": "UI & Math", "label": "快速置顶", "path": stroke((220, 520), (500, 260), 60) + " " + stroke((500, 260), (780, 520), 60) + " " + stroke((220, 740), (500, 480), 60) + " " + stroke((500, 480), (780, 740), 60)},
        {"name": "chevrons-down", "category": "UI & Math", "label": "快速置底", "path": stroke((220, 260), (500, 520), 60) + " " + stroke((500, 520), (780, 260), 60) + " " + stroke((220, 480), (500, 740), 60) + " " + stroke((500, 740), (780, 480), 60)},
        {"name": "chevrons-left", "category": "UI & Math", "label": "双向向左跳转", "path": stroke((520, 220), (260, 500), 60) + " " + stroke((260, 500), (520, 780), 60) + " " + stroke((740, 220), (480, 500), 60) + " " + stroke((480, 500), (740, 780), 60)},
        {"name": "chevrons-right", "category": "UI & Math", "label": "双向向右跳转", "path": stroke((260, 220), (520, 500), 60) + " " + stroke((520, 500), (260, 780), 60) + " " + stroke((480, 220), (740, 500), 60) + " " + stroke((740, 500), (480, 780), 60)},
        {"name": "arrow-up", "category": "UI & Math", "label": "向上箭头", "path": stroke((500, 800), (500, 200), 70) + " M 320 380 L 500 200 L 680 380 Z"},
        {"name": "arrow-down", "category": "UI & Math", "label": "向下箭头", "path": stroke((500, 200), (500, 800), 70) + " M 320 620 L 500 800 L 680 620 Z"},
        {"name": "arrow-left", "category": "UI & Math", "label": "向左箭头", "path": stroke((800, 500), (200, 500), 70) + " M 380 320 L 200 500 L 380 680 Z"},
        {"name": "arrow-right", "category": "UI & Math", "label": "向右箭头", "path": stroke((200, 500), (800, 500), 70) + " M 620 320 L 800 500 L 620 680 Z"},
        {"name": "arrow-up-right", "category": "UI & Math", "label": "外链右上跳转", "path": stroke((260, 740), (740, 260), 70) + " M 480 260 L 740 260 L 740 520 Z"},
        {"name": "arrow-down-left", "category": "UI & Math", "label": "对角左下跳转", "path": stroke((740, 260), (260, 740), 70) + " M 520 740 L 260 740 L 260 480 Z"},
        {"name": "corner-down-right", "category": "UI & Math", "label": "子分支向右转折", "path": stroke((300, 200), (300, 600), 60) + " " + stroke((300, 600), (700, 600), 60) + " M 580 480 L 740 600 L 580 720 Z"},
        {"name": "corner-up-left", "category": "UI & Math", "label": "向上回溯转折", "path": stroke((700, 800), (700, 400), 60) + " " + stroke((700, 400), (300, 400), 60) + " M 420 280 L 260 400 L 420 520 Z"},
        {"name": "undo", "category": "UI & Math", "label": "撤销操作 Undo", "path": arc(500, 520, 240, 200, 360, 60) + " M 400 200 L 240 340 L 400 480 Z"},
        {"name": "redo", "category": "UI & Math", "label": "重做操作 Redo", "path": arc(500, 520, 240, 180, 340, 60) + " M 600 200 L 760 340 L 600 480 Z"},
        {"name": "swap-h", "category": "UI & Math", "label": "水平对调", "path": stroke((200, 360), (760, 360), 50) + " M 640 260 L 780 360 L 640 460 Z " + stroke((800, 640), (240, 640), 50) + " M 360 540 L 220 640 L 360 740 Z"},
        {"name": "swap-v", "category": "UI & Math", "label": "垂直对调", "path": stroke((360, 200), (360, 760), 50) + " M 260 640 L 360 780 L 460 640 Z " + stroke((640, 800), (640, 240), 50) + " M 540 360 L 640 220 L 740 360 Z"},
        {"name": "check", "category": "UI & Math", "label": "确认勾选", "path": stroke((200, 520), (420, 740), 80) + " " + stroke((420, 740), (800, 260), 80)},
        {"name": "check-circle", "category": "UI & Math", "label": "成功圆环", "path": ring(500, 500, 400, 320) + " " + stroke((320, 500), (460, 640), 60) + " " + stroke((460, 640), (680, 380), 60)},
        {"name": "close", "category": "UI & Math", "label": "关闭取消", "path": stroke((240, 240), (760, 760), 80) + " " + stroke((760, 240), (240, 760), 80)},
        {"name": "close-circle", "category": "UI & Math", "label": "错误失败圆环", "path": ring(500, 500, 400, 320) + " " + stroke((350, 350), (650, 650), 60) + " " + stroke((650, 350), (350, 650), 60)},
        {"name": "alert", "category": "UI & Math", "label": "警告提示", "path": stroke((500, 200), (500, 600), 70) + " " + circle(500, 760, 45)},
        {"name": "alert-circle", "category": "UI & Math", "label": "警告圆环", "path": ring(500, 500, 400, 320) + " " + stroke((500, 300), (500, 580), 60) + " " + circle(500, 700, 40)},
        {"name": "alert-triangle", "category": "UI & Math", "label": "危险警示三角", "path": "M 500 140 L 880 800 L 120 800 Z M 500 240 L 260 740 L 740 740 Z " + stroke((500, 380), (500, 580), 50) + " " + circle(500, 680, 35)},
        {"name": "info", "category": "UI & Math", "label": "信息提示", "path": circle(500, 260, 45) + " " + stroke((500, 420), (500, 780), 70)},
        {"name": "info-circle", "category": "UI & Math", "label": "帮助信息圆环", "path": ring(500, 500, 400, 320) + " " + circle(500, 320, 40) + " " + stroke((500, 460), (500, 700), 60)},
        {"name": "help", "category": "UI & Math", "label": "问答疑问", "path": arc(500, 380, 160, 180, 360, 50) + " " + stroke((500, 500), (500, 600), 50) + " " + circle(500, 760, 45)},
        {"name": "help-circle", "category": "UI & Math", "label": "帮助中心圆环", "path": ring(500, 500, 400, 320) + " " + arc(500, 400, 120, 180, 360, 40) + " " + stroke((500, 500), (500, 580), 40) + " " + circle(500, 700, 35)},
        {"name": "bell", "category": "UI & Math", "label": "通知铃铛", "path": "M 500 160 C 360 160 300 280 300 480 L 220 680 L 780 680 L 700 480 C 700 280 640 160 500 160 Z " + circle(500, 780, 60)},
        {"name": "bell-off", "category": "UI & Math", "label": "静音免打扰", "path": "M 500 160 C 360 160 300 280 300 480 L 220 680 L 780 680 L 700 480 C 700 280 640 160 500 160 Z " + stroke((140, 140), (860, 860), 60)},
        {"name": "bell-ring", "category": "UI & Math", "label": "强提醒震动铃铛", "path": "M 500 160 C 360 160 300 280 300 480 L 220 680 L 780 680 L 700 480 C 700 280 640 160 500 160 Z " + arc(500, 500, 420, 140, 220, 50) + " " + arc(500, 500, 420, 320, 400, 50)},
        {"name": "clock", "category": "UI & Math", "label": "时钟计时", "path": ring(500, 500, 400, 320) + " " + stroke((500, 260), (500, 500), 50) + " " + stroke((500, 500), (680, 500), 50)},
        {"name": "calendar", "category": "UI & Math", "label": "日历日程", "path": frame(160, 200, 680, 640, 60, 50) + " " + stroke((160, 380), (840, 380), 50) + " " + stroke((320, 120), (320, 240), 50) + " " + stroke((680, 120), (680, 240), 50) + " " + circle(340, 520, 30) + " " + circle(500, 520, 30) + " " + circle(660, 520, 30) + " " + circle(340, 680, 30) + " " + circle(500, 680, 30)},
        {"name": "calendar-check", "category": "UI & Math", "label": "日程打卡", "path": frame(160, 200, 680, 640, 60, 50) + " " + stroke((160, 380), (840, 380), 50) + " " + stroke((320, 120), (320, 240), 50) + " " + stroke((680, 120), (680, 240), 50) + " " + stroke((360, 560), (460, 660), 50) + " " + stroke((460, 660), (660, 460), 50)},
        {"name": "hourglass", "category": "UI & Math", "label": "沙漏等待", "path": "M 260 180 L 740 180 L 500 500 L 740 820 L 260 820 L 500 500 Z M 320 240 L 680 240 L 500 480 Z M 500 520 L 680 760 L 320 760 Z"},
        {"name": "timer", "category": "UI & Math", "label": "精准计时器", "path": ring(500, 540, 360, 290) + " " + stroke((500, 540), (640, 400), 50) + " " + stroke((420, 140), (580, 140), 50) + " " + stroke((500, 140), (500, 240), 50)},
        {"name": "loader", "category": "UI & Math", "label": "异步加载中", "path": arc(500, 500, 360, 45, 315, 70)},
        {"name": "search", "category": "UI & Math", "label": "全局搜索", "path": ring(420, 420, 260, 190) + " " + stroke((600, 600), (840, 840), 70)},
        {"name": "zoom-in", "category": "UI & Math", "label": "放大查看", "path": ring(420, 420, 260, 190) + " " + stroke((600, 600), (840, 840), 70) + " " + stroke((320, 420), (520, 420), 40) + " " + stroke((420, 320), (420, 520), 40)},
        {"name": "zoom-out", "category": "UI & Math", "label": "缩小查看", "path": ring(420, 420, 260, 190) + " " + stroke((600, 600), (840, 840), 70) + " " + stroke((320, 420), (520, 420), 40)},
        {"name": "filter", "category": "UI & Math", "label": "条件过滤", "path": "M 180 200 L 820 200 L 560 520 L 560 800 L 440 840 L 440 520 Z"},
        {"name": "filter-clear", "category": "UI & Math", "label": "清空过滤", "path": "M 180 200 L 820 200 L 560 520 L 560 800 L 440 840 L 440 520 Z " + stroke((140, 140), (860, 860), 60)},
        {"name": "sort-asc", "category": "UI & Math", "label": "升序排列", "path": stroke((460, 280), (820, 280), 50) + " " + stroke((460, 500), (700, 500), 50) + " " + stroke((460, 720), (580, 720), 50) + " " + stroke((240, 760), (240, 240), 50) + " M 160 360 L 240 240 L 320 360 Z"},
        {"name": "sort-desc", "category": "UI & Math", "label": "降序排列", "path": stroke((460, 280), (580, 280), 50) + " " + stroke((460, 500), (700, 500), 50) + " " + stroke((460, 720), (820, 720), 50) + " " + stroke((240, 240), (240, 760), 50) + " M 160 640 L 240 760 L 320 640 Z"},
        {"name": "download", "category": "UI & Math", "label": "下载安装", "path": stroke((500, 180), (500, 640), 70) + " M 320 480 L 500 660 L 680 480 Z " + stroke((180, 820), (820, 820), 60)},
        {"name": "upload", "category": "UI & Math", "label": "上传分发", "path": stroke((500, 660), (500, 200), 70) + " M 320 380 L 500 200 L 680 380 Z " + stroke((180, 820), (820, 820), 60)},
        {"name": "export", "category": "UI & Math", "label": "数据导出", "path": frame(160, 240, 520, 600, 60, 50) + " " + stroke((420, 500), (840, 500), 60) + " M 700 360 L 840 500 L 700 640 Z"},
        {"name": "import", "category": "UI & Math", "label": "数据导入", "path": frame(160, 240, 520, 600, 60, 50) + " " + stroke((840, 500), (440, 500), 60) + " M 580 360 L 440 500 L 580 640 Z"},
        {"name": "share", "category": "UI & Math", "label": "分享传播", "path": circle(720, 280, 80) + " " + circle(280, 500, 80) + " " + circle(720, 720, 80) + " " + stroke((360, 460), (640, 320), 50) + " " + stroke((360, 540), (640, 680), 50)},
        {"name": "edit", "category": "UI & Math", "label": "编辑修改", "path": "M 200 800 L 320 780 L 740 360 L 640 260 L 220 680 Z M 600 220 L 700 120 L 820 240 L 720 340 Z"},
        {"name": "pen", "category": "UI & Math", "label": "签名钢笔", "path": "M 200 800 L 340 760 L 780 320 L 680 220 L 240 660 Z"},
        {"name": "trash", "category": "UI & Math", "label": "删除废弃", "path": frame(240, 320, 520, 500, 40, 45) + " " + stroke((160, 320), (840, 320), 60) + " " + frame(380, 160, 240, 160, 20, 30) + " " + stroke((380, 440), (380, 700), 40) + " " + stroke((500, 440), (500, 700), 40) + " " + stroke((620, 440), (620, 700), 40)},
        {"name": "archive", "category": "UI & Math", "label": "归档封存", "path": frame(160, 180, 680, 200, 30, 40) + " " + frame(200, 380, 600, 460, 30, 40) + " " + stroke((420, 520), (580, 520), 40)},
        {"name": "clipboard", "category": "UI & Math", "label": "剪贴板", "path": frame(200, 220, 600, 640, 60, 50) + " " + rect(360, 140, 280, 140, 30) + " " + stroke((320, 440), (680, 440), 40) + " " + stroke((320, 580), (680, 580), 40) + " " + stroke((320, 720), (520, 720), 40)},
        {"name": "clipboard-check", "category": "UI & Math", "label": "复制成功", "path": frame(200, 220, 600, 640, 60, 50) + " " + rect(360, 140, 280, 140, 30) + " " + stroke((360, 560), (460, 660), 45) + " " + stroke((460, 660), (640, 480), 45)},
        {"name": "copy", "category": "UI & Math", "label": "复制内容", "path": frame(340, 340, 500, 500, 60, 50) + " " + frame(160, 160, 500, 500, 60, 50)},
        {"name": "paste", "category": "UI & Math", "label": "粘贴内容", "path": frame(240, 240, 560, 600, 60, 50) + " " + rect(360, 160, 280, 140, 30) + " " + frame(140, 380, 300, 400, 30, 30)},
        {"name": "cut", "category": "UI & Math", "label": "剪切内容", "path": ring(300, 720, 120, 60) + " " + ring(700, 720, 120, 60) + " " + stroke((360, 640), (740, 220), 50) + " " + stroke((640, 640), (260, 220), 50)},
        {"name": "save", "category": "UI & Math", "label": "保存更改", "path": frame(160, 160, 680, 680, 60, 50) + " " + rect(280, 160, 440, 260, 20) + " " + rect(280, 540, 440, 300, 20) + " " + rect(360, 200, 100, 140, 10)},
        {"name": "settings", "category": "UI & Math", "label": "系统设置", "path": ring(500, 500, 380, 240) + " " + circle(500, 500, 120)},
        {"name": "sliders", "category": "UI & Math", "label": "偏好滑块", "path": stroke((160, 320), (840, 320), 40) + " " + stroke((160, 680), (840, 680), 40) + " " + rect(340, 240, 120, 160, 20) + " " + rect(540, 600, 120, 160, 20)},
        {"name": "user", "category": "UI & Math", "label": "开发者用户", "path": circle(500, 340, 140) + " M 220 780 C 220 620 340 560 500 560 C 660 560 780 620 780 780 Z"},
        {"name": "user-plus", "category": "UI & Math", "label": "添加成员", "path": circle(440, 340, 120) + " M 180 760 C 180 620 300 560 440 560 C 580 560 700 620 700 760 Z " + stroke((740, 340), (900, 340), 40) + " " + stroke((820, 260), (820, 420), 40)},
        {"name": "user-minus", "category": "UI & Math", "label": "移除成员", "path": circle(440, 340, 120) + " M 180 760 C 180 620 300 560 440 560 C 580 560 700 620 700 760 Z " + stroke((740, 340), (900, 340), 40)},
        {"name": "user-check", "category": "UI & Math", "label": "用户已认证", "path": circle(440, 340, 120) + " M 180 760 C 180 620 300 560 440 560 C 580 560 700 620 700 760 Z " + stroke((740, 340), (800, 400), 45) + " " + stroke((800, 400), (920, 280), 45)},
        {"name": "users", "category": "UI & Math", "label": "团队与组织", "path": circle(400, 320, 110) + " M 160 740 C 160 600 280 540 400 540 C 520 540 640 600 640 740 Z " + circle(650, 300, 90) + " M 640 540 C 720 560 840 620 840 740 Z"},
        {"name": "chat", "category": "UI & Math", "label": "交流讨论", "path": "M 160 220 L 840 220 C 880 220 900 240 900 280 L 900 640 C 900 680 880 700 840 700 L 360 700 L 200 840 L 200 700 L 160 700 C 120 700 100 680 100 640 L 100 280 C 100 240 120 220 160 220 Z"},
        {"name": "message-square", "category": "UI & Math", "label": "消息卡片", "path": "M 160 220 L 840 220 C 880 220 900 240 900 280 L 900 640 C 900 680 880 700 840 700 L 360 700 L 200 840 L 200 700 L 160 700 C 120 700 100 680 100 640 L 100 280 C 100 240 120 220 160 220 Z " + stroke((280, 460), (720, 460), 40)},
        {"name": "mail", "category": "UI & Math", "label": "邮件通知", "path": frame(140, 240, 720, 520, 60, 50) + " " + stroke((140, 240), (500, 520), 45) + " " + stroke((860, 240), (500, 520), 45)},
        {"name": "mail-open", "category": "UI & Math", "label": "阅读邮件", "path": frame(140, 360, 720, 440, 60, 50) + " " + stroke((140, 360), (500, 180), 45) + " " + stroke((860, 360), (500, 180), 45)},
        {"name": "send", "category": "UI & Math", "label": "发送信息", "path": "M 140 500 L 860 140 L 580 860 L 460 580 Z"},
        {"name": "inbox", "category": "UI & Math", "label": "收件箱", "path": frame(160, 220, 680, 600, 60, 50) + " " + stroke((160, 540), (340, 540), 45) + " " + stroke((340, 540), (420, 640), 45) + " " + stroke((420, 640), (580, 640), 45) + " " + stroke((580, 640), (660, 540), 45) + " " + stroke((660, 540), (840, 540), 45)},
        {"name": "thumbs-up", "category": "UI & Math", "label": "点赞推荐", "path": rect(140, 440, 160, 380, 20) + " M 300 440 L 460 160 C 500 160 540 200 540 260 L 540 440 L 800 440 C 860 440 900 480 880 540 L 820 800 C 800 840 760 840 700 840 L 300 840 Z"},
        {"name": "thumbs-down", "category": "UI & Math", "label": "反对点踩", "path": rect(140, 180, 160, 380, 20) + " M 300 560 L 460 840 C 500 840 540 800 540 740 L 540 560 L 800 560 C 860 560 900 520 880 460 L 820 200 C 800 160 760 160 700 160 L 300 160 Z"},
        {"name": "chart-bar", "category": "UI & Math", "label": "柱状分析图", "path": rect(180, 520, 140, 320, 20) + " " + rect(430, 320, 140, 520, 20) + " " + rect(680, 180, 140, 660, 20) + " " + stroke((100, 840), (900, 840), 50)},
        {"name": "chart-line", "category": "UI & Math", "label": "折线走势图", "path": stroke((100, 840), (900, 840), 50) + " " + stroke((180, 680), (420, 360), 60) + " " + stroke((420, 360), (640, 540), 60) + " " + stroke((640, 540), (840, 240), 60) + " " + circle(180, 680, 35) + " " + circle(420, 360, 35) + " " + circle(640, 540, 35) + " " + circle(840, 240, 35)},
        {"name": "chart-pie", "category": "UI & Math", "label": "饼图占比", "path": ring(500, 500, 400, 320) + " M 500 500 L 500 140 A 360 360 0 0 1 860 500 Z"},
        {"name": "chart-area", "category": "UI & Math", "label": "堆叠面积图", "path": stroke((100, 840), (900, 840), 50) + " M 160 840 L 160 620 L 400 380 L 640 520 L 840 280 L 840 840 Z"},
        {"name": "activity", "category": "UI & Math", "label": "实时心跳活跃度", "path": stroke((120, 500), (320, 500), 60) + " " + stroke((320, 500), (440, 200), 60) + " " + stroke((440, 200), (560, 800), 60) + " " + stroke((560, 800), (680, 500), 60) + " " + stroke((680, 500), (880, 500), 60)},
        {"name": "trending-up", "category": "UI & Math", "label": "向上突破增长", "path": stroke((160, 680), (420, 420), 60) + " " + stroke((420, 420), (580, 580), 60) + " " + stroke((580, 580), (840, 320), 60) + " M 640 320 L 840 320 L 840 520 Z"},
        {"name": "trending-down", "category": "UI & Math", "label": "向下波动下降", "path": stroke((160, 320), (420, 580), 60) + " " + stroke((420, 580), (580, 420), 60) + " " + stroke((580, 420), (840, 680), 60) + " M 640 680 L 840 680 L 840 480 Z"},
        {"name": "presentation", "category": "UI & Math", "label": "演示汇报大屏", "path": frame(140, 180, 720, 480, 60, 50) + " " + stroke((500, 660), (500, 840), 50) + " " + stroke((360, 840), (640, 840), 50) + " " + stroke((300, 340), (700, 340), 40) + " " + stroke((300, 460), (560, 460), 40)},
        {"name": "dashboard", "category": "UI & Math", "label": "监控仪表大盘", "path": frame(120, 160, 760, 680, 80, 60) + " " + rect(220, 260, 240, 240, 30) + " " + rect(540, 260, 240, 240, 30) + " " + rect(220, 560, 560, 180, 30)},
        {"name": "calculator", "category": "UI & Math", "label": "科学计算器", "path": frame(200, 140, 600, 720, 60, 50) + " " + rect(280, 220, 440, 160, 20) + " " + circle(360, 480, 35) + " " + circle(500, 480, 35) + " " + circle(640, 480, 35) + " " + circle(360, 620, 35) + " " + circle(500, 620, 35) + " " + circle(640, 620, 35) + " " + circle(360, 740, 35) + " " + circle(500, 740, 35) + " " + circle(640, 740, 35)},
        {"name": "plus", "category": "UI & Math", "label": "加号 +", "path": stroke((200, 500), (800, 500), 70) + " " + stroke((500, 200), (500, 800), 70)},
        {"name": "minus", "category": "UI & Math", "label": "减号 -", "path": stroke((200, 500), (800, 500), 70)},
        {"name": "multiply", "category": "UI & Math", "label": "乘号 ×", "path": stroke((260, 260), (740, 740), 70) + " " + stroke((740, 260), (260, 740), 70)},
        {"name": "divide", "category": "UI & Math", "label": "除号 ÷", "path": stroke((200, 500), (800, 500), 70) + " " + circle(500, 280, 45) + " " + circle(500, 720, 45)},
        {"name": "percent", "category": "UI & Math", "label": "百分比 %", "path": stroke((740, 240), (260, 760), 60) + " " + circle(340, 340, 70) + " " + circle(660, 660, 70)},
        {"name": "infinity", "category": "UI & Math", "label": "无穷大 ∞", "path": ring(350, 500, 180, 110) + " " + ring(650, 500, 180, 110)},
        {"name": "pi", "category": "UI & Math", "label": "圆周率 π", "path": stroke((200, 240), (800, 240), 70) + " " + stroke((360, 240), (360, 760), 60) + " " + stroke((640, 240), (640, 760), 60)},
        {"name": "sigma", "category": "UI & Math", "label": "求和符号 ∑", "path": stroke((760, 220), (280, 220), 70) + " " + stroke((280, 220), (520, 500), 70) + " " + stroke((520, 500), (280, 780), 70) + " " + stroke((280, 780), (760, 780), 70)},
        {"name": "function-fx", "category": "UI & Math", "label": "函数映射 f(x)", "path": arc(460, 340, 140, 180, 360, 60) + " " + stroke((460, 340), (460, 780), 60) + " " + stroke((240, 460), (520, 460), 50) + " " + stroke((620, 600), (780, 760), 40) + " " + stroke((780, 600), (620, 760), 40)},
        {"name": "compass", "category": "UI & Math", "label": "圆规绘图", "path": stroke((500, 160), (260, 840), 50) + " " + stroke((500, 160), (740, 840), 50) + " " + circle(500, 160, 40) + " " + arc(500, 160, 440, 50, 130, 40)},
        {"name": "ruler", "category": "UI & Math", "label": "刻度量尺", "path": frame(160, 360, 680, 280, 40, 50) + " " + stroke((280, 360), (280, 480), 40) + " " + stroke((400, 360), (400, 440), 40) + " " + stroke((520, 360), (520, 480), 40) + " " + stroke((640, 360), (640, 440), 40)},
        {"name": "flask", "category": "UI & Math", "label": "实验试管", "path": "M 420 160 L 580 160 L 580 340 L 780 720 C 820 800 760 860 680 860 L 320 860 C 240 860 180 800 220 720 L 420 340 Z " + stroke((300, 680), (700, 680), 40)},
        {"name": "atom", "category": "UI & Math", "label": "原子物理模型", "path": circle(500, 500, 90) + " " + ring(500, 500, 380, 330) + " " + ring(500, 500, 240, 190)},
        {"name": "dna", "category": "UI & Math", "label": "基因双螺旋", "path": arc(500, 320, 240, 180, 360, 50) + " " + arc(500, 680, 240, 0, 180, 50) + " " + stroke((320, 300), (680, 300), 40) + " " + stroke((320, 700), (680, 700), 40) + " " + stroke((260, 500), (740, 500), 40)},
        {"name": "magnet", "category": "UI & Math", "label": "强力磁场", "path": arc(500, 460, 260, 0, 180, 80) + " " + stroke((240, 460), (240, 200), 80) + " " + stroke((760, 460), (760, 200), 80) + " " + rect(200, 160, 80, 80, 10) + " " + rect(720, 160, 80, 80, 10)}
    ]

def get_all_icons_data(helpers):
    all_icons = []
    all_icons.extend(get_brand_icons(helpers))
    all_icons.extend(get_language_icons(helpers))
    all_icons.extend(get_compiler_icons(helpers))
    all_icons.extend(get_devtools_icons(helpers))
    all_icons.extend(get_git_devops_icons(helpers))
    all_icons.extend(get_network_icons(helpers))
    all_icons.extend(get_database_icons(helpers))
    all_icons.extend(get_security_icons(helpers))
    all_icons.extend(get_files_media_icons(helpers))
    all_icons.extend(get_hardware_devices_icons(helpers))
    all_icons.extend(get_ui_charts_math_icons(helpers))

    # Assign deterministic Unicode codepoints starting from 0xE900
    base_code = 0xE900
    for idx, icon in enumerate(all_icons):
        icon["code"] = base_code + idx

    return all_icons
