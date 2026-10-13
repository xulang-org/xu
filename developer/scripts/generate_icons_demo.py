import os
import json

def generate_demo(json_path, css_path, out_html_path):
    data = json.load(open(json_path, encoding='utf-8'))
    icons = data['icons']
    categories = data.get('categories', [])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>XuIcons (v1.1.0) — XU 官方全场景高精字体图标库 (145+ Icons)</title>
  <link rel="stylesheet" href="fonts/xu-icons.css">
  <style>
    :root {{
      --xu-bg: #0A090D;
      --xu-surface: #121118;
      --xu-surface-card: #181622;
      --xu-border: rgba(255, 255, 255, 0.08);
      --xu-text-main: #F8FAFC;
      --xu-text-sub: #94A3B8;
      --xu-brand: #E11D48;
      --xu-brand-glow: #FF385C;
      --xu-amber: #F59E0B;
      --xu-cyan: #38BDF8;
      --xu-green: #10B981;
    }}
    [data-theme="light"] {{
      --xu-bg: #F8F9FA;
      --xu-surface: #FFFFFF;
      --xu-surface-card: #F3F4F6;
      --xu-border: #E5E7EB;
      --xu-text-main: #111827;
      --xu-text-sub: #4B5563;
      --xu-brand: #BE123C;
      --xu-brand-glow: #E11D48;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans SC", sans-serif;
      background: var(--xu-bg);
      color: var(--xu-text-main);
      line-height: 1.5;
      padding: 0 0 80px 0;
      transition: background 0.2s, color 0.2s;
    }}

    /* Header */
    .header {{
      background: var(--xu-surface);
      border-bottom: 1px solid var(--xu-border);
      padding: 18px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(12px);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .brand-icon {{
      font-size: 32px;
      color: var(--xu-brand-glow);
    }}
    .brand-title {{
      font-size: 20px;
      font-weight: 900;
      letter-spacing: -0.5px;
    }}
    .badge {{
      background: rgba(225, 29, 72, 0.15);
      color: var(--xu-brand-glow);
      border: 1px solid rgba(225, 29, 72, 0.3);
      padding: 2px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-family: monospace;
      font-weight: 700;
    }}

    /* Hero */
    .hero {{
      max-width: 1200px;
      margin: 36px auto 24px;
      padding: 0 24px;
      text-align: center;
    }}
    .hero h1 {{
      font-size: 34px;
      font-weight: 900;
      margin-bottom: 12px;
      letter-spacing: -1px;
    }}
    .hero p {{
      color: var(--xu-text-sub);
      font-size: 15px;
      max-width: 720px;
      margin: 0 auto 20px;
    }}
    .stats-bar {{
      display: inline-flex;
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      border-radius: 30px;
      padding: 6px 20px;
      gap: 20px;
      font-size: 13px;
      font-family: monospace;
      color: var(--xu-text-sub);
      flex-wrap: wrap;
      justify-content: center;
    }}
    .stats-bar span b {{
      color: var(--xu-text-main);
    }}

    /* Toolbar */
    .toolbar-wrapper {{
      max-width: 1200px;
      margin: 0 auto 20px;
      padding: 0 24px;
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      justify-content: space-between;
      align-items: center;
    }}
    .search-box {{
      position: relative;
      flex: 1;
      min-width: 280px;
      max-width: 460px;
    }}
    .search-box i {{
      position: absolute;
      left: 14px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--xu-text-sub);
      font-size: 16px;
    }}
    .search-input {{
      width: 100%;
      padding: 12px 16px 12px 42px;
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      border-radius: 10px;
      color: var(--xu-text-main);
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }}
    .search-input:focus {{
      border-color: var(--xu-brand-glow);
    }}
    .control-group {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .size-slider-wrap {{
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      padding: 8px 16px;
      border-radius: 10px;
      font-size: 12px;
      font-family: monospace;
    }}
    .size-slider {{
      accent-color: var(--xu-brand);
      cursor: pointer;
    }}
    .btn-theme {{
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      color: var(--xu-text-main);
      padding: 8px 16px;
      border-radius: 10px;
      cursor: pointer;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .btn-theme:hover {{
      border-color: var(--xu-brand);
    }}

    /* Tabs */
    .tabs-bar {{
      max-width: 1200px;
      margin: 0 auto 24px;
      padding: 0 24px;
      display: flex;
      gap: 10px;
      overflow-x: auto;
      scrollbar-width: none;
    }}
    .tab-btn {{
      padding: 8px 16px;
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      color: var(--xu-text-sub);
      border-radius: 8px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      white-space: nowrap;
      transition: all 0.2s;
    }}
    .tab-btn:hover {{
      color: var(--xu-text-main);
    }}
    .tab-btn.active {{
      background: var(--xu-brand);
      color: #FFFFFF;
      border-color: var(--xu-brand);
    }}

    /* Grid */
    .grid-container {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 24px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
      gap: 14px;
    }}
    .icon-card {{
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      border-radius: 12px;
      padding: 22px 14px 14px;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      cursor: pointer;
      position: relative;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }}
    .icon-card:hover {{
      transform: translateY(-3px);
      border-color: var(--xu-brand);
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }}
    .icon-preview {{
      font-size: 36px;
      margin-bottom: 14px;
      color: var(--xu-text-main);
      transition: font-size 0.1s, color 0.2s;
      min-height: 48px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .icon-card:hover .icon-preview {{
      color: var(--xu-brand-glow);
    }}
    .icon-name {{
      font-size: 12px;
      font-weight: 700;
      font-family: monospace;
      color: var(--xu-text-main);
      margin-bottom: 4px;
      word-break: break-all;
    }}
    .icon-unicode {{
      font-size: 11px;
      font-family: monospace;
      color: var(--xu-text-sub);
      margin-bottom: 4px;
    }}
    .icon-label {{
      font-size: 11px;
      color: var(--xu-text-sub);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 100%;
    }}

    /* Code Quickstart */
    .usage-section {{
      max-width: 1200px;
      margin: 60px auto 0;
      padding: 0 24px;
    }}
    .usage-card {{
      background: var(--xu-surface);
      border: 1px solid var(--xu-border);
      border-radius: 16px;
      padding: 32px;
    }}
    .usage-card h2 {{
      font-size: 20px;
      font-weight: 900;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .code-block {{
      background: #050508;
      border: 1px solid var(--xu-border);
      border-radius: 10px;
      padding: 16px 20px;
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      color: #E2E8F0;
      margin-bottom: 16px;
      overflow-x: auto;
    }}

    /* Toast */
    .toast {{
      position: fixed;
      bottom: 30px;
      right: 30px;
      background: var(--xu-surface-card);
      border: 1px solid var(--xu-brand);
      color: var(--xu-text-main);
      padding: 12px 24px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
      z-index: 999;
      opacity: 0;
      transform: translateY(20px);
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      pointer-events: none;
    }}
    .toast.show {{
      opacity: 1;
      transform: translateY(0);
    }}
  </style>
</head>
<body>

  <header class="header">
    <div class="brand">
      <i class="xi xi-logo brand-icon"></i>
      <span class="brand-title">XuIcons</span>
      <span class="badge">v1.1.0 · 145 Icons</span>
    </div>
    <div style="display:flex; gap:12px; align-items:center;">
      <a href="index.html" style="color:var(--xu-text-sub); text-decoration:none; font-size:13px; font-weight:600;"><i class="xi xi-home"></i> 返回主页</a>
      <a href="office_merch.html" style="color:var(--xu-text-sub); text-decoration:none; font-size:13px; font-weight:600;"><i class="xi xi-package"></i> 物料展厅</a>
      <button class="btn-theme" id="theme-btn" onclick="toggleTheme()"><i class="xi xi-moon"></i> <span>暗黑模式</span></button>
    </div>
  </header>

  <main class="hero">
    <h1>XU 官方全场景高精字体图标库</h1>
    <p>为 XU 编程语言生态、XUFLOW 流程图审查系统、UI 桌面/Web 展厅专属打造的矢量字体图标套件。包含品牌、编译器、IDE、网络云原生、界面控件与硬件外设全领域。</p>
    <div class="stats-bar">
      <span><b>{len(icons)}</b> 款全场景矢量图标</span>
      <span><b>6</b> 大专业分类</span>
      <span><b>3</b> 种工业格式 (TTF / WOFF / SVG)</span>
      <span>WOFF 体积 <b>11.1 KB</b></span>
      <span>前缀 <b>.xi .xi-*</b></span>
    </div>
  </main>

  <div class="toolbar-wrapper">
    <div class="search-box">
      <i class="xi xi-search"></i>
      <input type="text" id="search-input" class="search-input" placeholder="搜索图标名称、拼音或用途 (如: logo, flow, coroutine, server, git)...">
    </div>
    <div class="control-group">
      <div class="size-slider-wrap">
        <span>字号:</span>
        <input type="range" id="size-slider" class="size-slider" min="16" max="72" value="36">
        <span id="size-val">36px</span>
      </div>
    </div>
  </div>

  <div class="tabs-bar">
    <button class="tab-btn active" data-cat="All" onclick="filterCategory('All')">全部图标 ({len(icons)})</button>
"""
    for cat in categories:
        html += f"""    <button class="tab-btn" data-cat="{cat['id']}" onclick="filterCategory('{cat['id']}')">{cat['name']} ({cat['count']})</button>\n"""

    html += f"""  </div>

  <div class="grid-container" id="icons-grid">
"""
    for icon in icons:
        html += f"""    <div class="icon-card" data-name="{icon['name']}" data-cat="{icon['category']}" data-label="{icon['label']}" onclick="copyIconClass('xi-{icon['name']}', '{icon['name']}')">
      <div class="icon-preview"><i class="xi xi-{icon['name']}"></i></div>
      <div class="icon-name">xi-{icon['name']}</div>
      <div class="icon-unicode">{icon['unicode']}</div>
      <div class="icon-label">{icon['label']}</div>
    </div>
"""

    html += f"""  </div>

  <section class="usage-section">
    <div class="usage-card">
      <h2><i class="xi xi-code xi-brand"></i> 快速上手与集成指南 (Quick Start)</h2>

      <p style="color:var(--xu-text-sub); margin-bottom:12px;">1. 在 HTML 中引入字体样式表：</p>
      <div class="code-block">&lt;link rel="stylesheet" href="fonts/xu-icons.css"&gt;</div>

      <p style="color:var(--xu-text-sub); margin-bottom:12px;">2. 在 HTML 中调用图标类：</p>
      <div class="code-block">&lt;!-- 官方 LOGO --&gt;
&lt;i class="xi xi-logo"&gt;&lt;/i&gt;

&lt;!-- XUFLOW 流程图审查标 --&gt;
&lt;i class="xi xi-xuflow xi-brand"&gt;&lt;/i&gt;

&lt;!-- 并发协程 & CSP 信道 --&gt;
&lt;i class="xi xi-coroutine xi-cyan"&gt;&lt;/i&gt;
&lt;i class="xi xi-channel xi-green"&gt;&lt;/i&gt;

&lt;!-- 尺寸与动画辅助类 (.xi-spin, .xi-2x) --&gt;
&lt;i class="xi xi-refresh xi-spin xi-2x"&gt;&lt;/i&gt;</div>

      <p style="color:var(--xu-text-sub); margin-bottom:12px;">3. 在 CSS 伪元素中使用：</p>
      <div class="code-block">.btn-submit:before {{
  font-family: 'XuIcons';
  content: "\\e954"; /* xi-check */
  margin-right: 8px;
}}</div>
    </div>
  </section>

  <div class="toast" id="toast"><i class="xi xi-check xi-green"></i> <span id="toast-msg">已复制到剪贴板</span></div>

  <script>
    function showToast(msg) {{
      const toast = document.getElementById('toast');
      document.getElementById('toast-msg').textContent = msg;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 2000);
    }}

    function copyIconClass(cls, name) {{
      const snippet = `<i class="xi ${{cls}}"></i>`;
      navigator.clipboard.writeText(snippet).then(() => {{
        showToast(`已复制: ${{snippet}}`);
      }}).catch(() => {{
        showToast(`图标名: ${{cls}}`);
      }});
    }}

    function toggleTheme() {{
      const cur = document.documentElement.getAttribute('data-theme');
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      const btn = document.getElementById('theme-btn');
      btn.innerHTML = next === 'dark' ? '<i class="xi xi-moon"></i> <span>暗黑模式</span>' : '<i class="xi xi-sun"></i> <span>明亮模式</span>';
    }}

    // Sizing
    const slider = document.getElementById('size-slider');
    const sizeVal = document.getElementById('size-val');
    slider.addEventListener('input', (e) => {{
      const val = e.target.value;
      sizeVal.textContent = `${{val}}px`;
      document.querySelectorAll('.icon-preview').forEach(el => {{
        el.style.fontSize = `${{val}}px`;
      }});
    }});

    // Category Filter
    let activeCategory = 'All';
    function filterCategory(cat) {{
      activeCategory = cat;
      document.querySelectorAll('.tab-btn').forEach(btn => {{
        btn.classList.toggle('active', btn.getAttribute('data-cat') === cat);
      }});
      applyFilter();
    }}

    // Search Filter
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', applyFilter);

    function applyFilter() {{
      const q = searchInput.value.toLowerCase().trim();
      document.querySelectorAll('.icon-card').forEach(card => {{
        const name = card.getAttribute('data-name').toLowerCase();
        const cat = card.getAttribute('data-cat');
        const label = card.getAttribute('data-label').toLowerCase();

        const matchesCat = (activeCategory === 'All' || cat === activeCategory);
        const matchesSearch = (!q || name.includes(q) || label.includes(q));

        card.style.display = (matchesCat && matchesSearch) ? 'flex' : 'none';
      }});
    }}
  </script>
</body>
</html>
"""
    with open(out_html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✓ Generated Demo HTML: {out_html_path}")

if __name__ == '__main__':
    base_dir = '/Users/dmy/work/xu/brand/fonts/xu-icons'
    generate_demo(
        os.path.join(base_dir, 'xu-icons.json'),
        os.path.join(base_dir, 'xu-icons.css'),
        os.path.join(base_dir, 'demo.html')
    )
