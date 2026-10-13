(function () {
  const KW = {
    if: 1, match: 1, while: 1, for: 1, in: 1, else: 1, fn: 1, true: 1,
    false: 1, done: 1, loop: 1, next: 1, join: 1, int: 1, string: 1,
    bool: 1, mut: 1, pub: 1, return: 1, call: 1
  };
  const BOX_W = 200, BOX_H = 56, DIA_H = 72, CARD_W = 220, CARD_H = 48;
  const COL_GAP = 256, ROW = 124, PAD = 22, TOP = 38;

  const state = {
    root: "",
    err: "",
    nodes: [],
    edges: [],
    own: [],
    pos: [],
    open: new Set(),
    binds: {},
    lit: new Set(),
    focus: -1,
    depth: [],
    tx: 32,
    ty: 16,
    scale: 1
  };

  const world = document.getElementById("world");
  const cv = document.getElementById("cv");
  const treeEl = document.getElementById("tree");
  const bindsEl = document.getElementById("binds");
  const rootEl = document.getElementById("root");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  function clip(s, n) {
    s = String(s || "");
    if (s.length <= n) return s;
    return s.slice(0, n - 2) + "..";
  }

  function isFn(lab) {
    return lab.slice(0, 3) === "fn ";
  }

  function isLetter(c) {
    return (c >= 97 && c <= 122) || (c >= 65 && c <= 90) || c === 95;
  }

  function firstIdent(s) {
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      if (!isLetter(c)) continue;
      let j = i + 1;
      while (j < s.length) {
        const d = s.charCodeAt(j);
        if (isLetter(d) || (d >= 48 && d <= 57)) j++;
        else break;
      }
      const w = s.slice(i, j);
      if (!KW[w]) return w;
      i = j - 1;
    }
    return "";
  }

  function fnName(lab) {
    if (!isFn(lab)) return "";
    let rest = lab.slice(3);
    let i = 0;
    while (i < rest.length && rest.charCodeAt(i) === 32) i++;
    if (i < rest.length && rest.charCodeAt(i) === 40) {
      while (i < rest.length && rest.charCodeAt(i) !== 41) i++;
      if (i < rest.length) i++;
      while (i < rest.length && rest.charCodeAt(i) === 32) i++;
    }
    let j = i;
    while (j < rest.length) {
      const c = rest.charCodeAt(j);
      if (isLetter(c) || (c >= 48 && c <= 57)) j++;
      else break;
    }
    return rest.slice(i, j);
  }

  function fnParamsInner(lab) {
    const a = lab.lastIndexOf("(");
    const b = lab.lastIndexOf(")");
    if (a >= 0 && b > a) return lab.slice(a + 1, b);
    return "";
  }

  function nodeBindName(ni) {
    const lab = state.nodes[ni].label;
    if (isFn(lab)) return firstIdent(fnParamsInner(lab));
    const w = firstIdent(lab);
    if (w) return w;
    const id = state.nodes[ni].id;
    for (let e = 0; e < state.edges.length; e++) {
      if (state.edges[e].a === id) {
        const w2 = firstIdent(state.edges[e].lab);
        if (w2) return w2;
      }
    }
    return "";
  }

  function noteOf(i) {
    const n = state.nodes[i];
    return n && n.note ? String(n.note) : "";
  }

  function boxH(i) {
    return state.nodes[i].shape === 1 ? DIA_H : BOX_H;
  }

  function cardH(owner) {
    return CARD_H;
  }

  function regionTop(owner) {
    return TOP;
  }

  function ixOf(id) {
    for (let i = 0; i < state.nodes.length; i++) {
      if (state.nodes[i].id === id) return i;
    }
    return -1;
  }

  function parseDump(raw) {
    const sep = String.fromCharCode(30);
    const recs = String(raw || "").split(sep);
    const nodes = [];
    const edges = [];
    const binds = {};
    let root = "";
    let err = "";
    for (let i = 0; i < recs.length; i++) {
      const ln = recs[i];
      if (!ln) continue;
      const parts = ln.split("\t");
      const tag = parts[0];
      if (tag === "ROOT") root = parts.slice(1).join("\t");
      else if (tag === "ERR") err = parts.slice(1).join("\t");
      else if (tag === "N" && parts.length >= 4) {
        nodes.push({ id: +parts[1], shape: +parts[2], label: parts.slice(3).join("\t"), note: "" });
      } else if (tag === "E" && parts.length >= 3) {
        edges.push({ a: +parts[1], b: +parts[2], lab: parts.slice(3).join("\t") });
      } else if (tag === "C" && parts.length >= 3) {
        const id = +parts[1];
        const note = parts.slice(2).join("\t");
        for (let j = 0; j < nodes.length; j++) {
          if (nodes[j].id === id) { nodes[j].note = note; break; }
        }
      } else if (tag === "S" && parts.length >= 2) {
        binds[parts[1]] = parts.slice(2).join("\t");
      }
    }
    return { root, err, nodes, edges, binds };
  }

  function floodOwn() {
    const n = state.nodes.length;
    const own = new Array(n).fill(-1);
    const idTo = new Map();
    for (let i = 0; i < n; i++) idTo.set(state.nodes[i].id, i);
    function flood(startId, owner) {
      const q = [startId];
      for (let qi = 0; qi < q.length; qi++) {
        const id = q[qi];
        const ix = idTo.get(id);
        if (ix === undefined || own[ix] >= 0) continue;
        own[ix] = owner;
        for (let e = 0; e < state.edges.length; e++) {
          const ed = state.edges[e];
          if (ed.lab === "call") continue;
          if (ed.a === id) q.push(ed.b);
        }
      }
    }
    for (let i = 0; i < n; i++) {
      if (isFn(state.nodes[i].label)) flood(state.nodes[i].id, i);
    }
    state.own = own;
  }

  function depths() {
    const n = state.nodes.length;
    const d = new Array(n).fill(0);
    const idTo = new Map();
    for (let i = 0; i < n; i++) idTo.set(state.nodes[i].id, i);
    for (let it = 0; it < n; it++) {
      for (let e = 0; e < state.edges.length; e++) {
        const ed = state.edges[e];
        if (ed.lab === "loop" || ed.lab === "next" || ed.lab === "call") continue;
        const a = idTo.get(ed.a);
        const b = idTo.get(ed.b);
        if (a == null || b == null) continue;
        if (d[b] < d[a] + 1) d[b] = d[a] + 1;
      }
    }
    return d;
  }

  function isOpen(owner) {
    return state.open.has(owner);
  }

  function toggleFn(fi) {
    if (state.open.has(fi)) state.open.delete(fi);
    else state.open.add(fi);
    state.focus = fi;
    render();
  }

  function layoutCollapsed(owner, cursorX, pos) {
    const n = state.nodes.length;
    let saw = 0;
    for (let j = 0; j < n; j++) {
      if (state.own[j] !== owner) continue;
      saw = 1;
      pos[j] = { x: cursorX, y: 120, w: CARD_W, h: cardH(owner) };
    }
    return saw ? cursorX + COL_GAP : cursorX;
  }

  function layoutColumn(owner, cursorX, pos, depth) {
    const n = state.nodes.length;
    let maxd = 0;
    let saw = 0;
    for (let j = 0; j < n; j++) {
      if (state.own[j] !== owner) continue;
      saw = 1;
      if (depth[j] > maxd) maxd = depth[j];
    }
    if (!saw) return cursorX;
    const counts = new Array(maxd + 1).fill(0);
    for (let j = 0; j < n; j++) {
      if (state.own[j] !== owner) continue;
      const d = depth[j];
      const slot = counts[d];
      const h = boxH(j);
      pos[j] = { x: cursorX + slot * 216, y: 120 + d * ROW, w: BOX_W, h: h };
      counts[d] = slot + 1;
    }
    let cols = 1;
    for (let s = 0; s < counts.length; s++) if (counts[s] > cols) cols = counts[s];
    return cursorX + cols * 216 + 160;
  }

  function layout() {
    floodOwn();
    const n = state.nodes.length;
    const depth = depths();
    const pos = new Array(n);
    for (let i = 0; i < n; i++) pos[i] = { x: 0, y: 120, w: BOX_W, h: boxH(i) };
    const placed = new Array(n).fill(0);
    const q = [];
    for (let i = 0; i < n; i++) {
      if (isFn(state.nodes[i].label) && fnName(state.nodes[i].label) === "main") q.push(i);
    }
    let cursor = 40;
    for (let qi = 0; qi < q.length; qi++) {
      const fi = q[qi];
      if (placed[fi]) continue;
      placed[fi] = 1;
      cursor = isOpen(fi) ? layoutColumn(fi, cursor, pos, depth) : layoutCollapsed(fi, cursor, pos);
      for (let e = 0; e < state.edges.length; e++) {
        const ed = state.edges[e];
        if (ed.lab !== "call") continue;
        const src = ixOf(ed.a);
        if (src < 0 || state.own[src] !== fi) continue;
        const dst = ixOf(ed.b);
        if (dst >= 0 && !placed[dst]) q.push(dst);
      }
    }
    for (let i = 0; i < n; i++) {
      if (!isFn(state.nodes[i].label) || placed[i]) continue;
      placed[i] = 1;
      cursor = isOpen(i) ? layoutColumn(i, cursor, pos, depth) : layoutCollapsed(i, cursor, pos);
    }
    for (let j = 0; j < n; j++) {
      if (state.own[j] >= 0) continue;
      pos[j] = { x: cursor, y: 120, w: BOX_W, h: boxH(j) };
      cursor += 216;
    }
    state.pos = pos;
    state.depth = depth;
  }

  function ownerBBox(owner) {
    const n = state.nodes.length;
    if (!isOpen(owner)) {
      for (let j = 0; j < n; j++) {
        if (state.own[j] === owner) {
          const p = state.pos[j];
          return { x: p.x - 10, y: p.y - 8, w: CARD_W + 20, h: cardH(owner) + 16 };
        }
      }
      return { x: 0, y: 0, w: 0, h: 0 };
    }
    let minx = 0, miny = 0, maxx = 0, maxy = 0, saw = 0;
    for (let j = 0; j < n; j++) {
      if (state.own[j] !== owner) continue;
      const p = state.pos[j];
      const w = BOX_W;
      const h = p.h || boxH(j);
      if (!saw) {
        minx = p.x; miny = p.y; maxx = p.x + w; maxy = p.y + h; saw = 1;
      } else {
        if (p.x < minx) minx = p.x;
        if (p.y < miny) miny = p.y;
        if (p.x + w > maxx) maxx = p.x + w;
        if (p.y + h > maxy) maxy = p.y + h;
      }
    }
    if (!saw) return { x: 0, y: 0, w: 0, h: 0 };
    const top = regionTop(owner);
    return { x: minx - PAD, y: miny - top, w: maxx - minx + PAD * 2, h: maxy - miny + top + PAD };
  }

  function pushPt(pts, x, y) {
    const last = pts[pts.length - 1];
    if (last && last[0] === x && last[1] === y) return;
    pts.push([x, y]);
  }

  function callSlot(e) {
    let k = 0;
    for (let i = 0; i < e; i++) if (state.edges[i].lab === "call") k++;
    return k;
  }

  function callRoute(na, nb, slot) {
    const oa = state.own[na];
    const ob = state.own[nb];
    let aw = BOX_W, ah = state.pos[na].h || boxH(na);
    let bw = BOX_W, bh = state.pos[nb].h || boxH(nb);
    if (!isOpen(oa)) { aw = CARD_W; ah = cardH(oa); }
    if (!isOpen(ob)) { bw = CARD_W; bh = cardH(ob); }
    const ra = ownerBBox(oa);
    const rb = ownerBBox(ob);
    const gap = 20;
    const nx1 = state.pos[na].x, ny1 = state.pos[na].y;
    const nx2 = state.pos[nb].x, ny2 = state.pos[nb].y;
    const y1 = ny1 + ah / 2;
    const y2 = ny2 + bh / 2;
    const cx2 = nx2 + bw / 2;
    let rightward = 1;
    if (rb.w > 0 && ra.w > 0) {
      if (rb.x + rb.w / 2 < ra.x + ra.w / 2) rightward = 0;
    } else if (nx2 < nx1) rightward = 0;
    let x1 = nx1 + aw;
    let x2 = nx2;
    if (!rightward) {
      x1 = nx1;
      x2 = nx2 + bw;
    }
    const pts = [];
    if (ra.w === 0 || rb.w === 0) {
      pushPt(pts, x1, y1);
      pushPt(pts, x2, y2);
      return pts;
    }
    if (oa === ob) {
      const xOut = ra.x + ra.w + gap + (slot % 4) * 10;
      let yTop = ny2 - 16;
      if (yTop > ra.y - 12) yTop = ra.y - 12;
      yTop -= (slot % 3) * 8;
      pushPt(pts, x1, y1);
      pushPt(pts, xOut, y1);
      pushPt(pts, xOut, yTop);
      pushPt(pts, cx2, yTop);
      pushPt(pts, cx2, ny2);
      return pts;
    }
    let adj = 0;
    if (rightward) {
      if (rb.x >= ra.x + ra.w - 8 && rb.x <= ra.x + ra.w + 240) adj = 1;
    } else if (ra.x >= rb.x + rb.w - 8 && ra.x <= rb.x + rb.w + 240) adj = 1;
    if (adj) {
      let xMid = rightward ? (ra.x + ra.w + rb.x) / 2 : (rb.x + rb.w + ra.x) / 2;
      xMid += (slot % 5) * 6 - 12;
      pushPt(pts, x1, y1);
      pushPt(pts, xMid, y1);
      pushPt(pts, xMid, y2);
      pushPt(pts, x2, y2);
      return pts;
    }
    let rail = ra.y;
    if (rb.y < rail) rail = rb.y;
    rail = rail - 14 - (slot % 7) * 11;
    let xOut = rightward ? ra.x + ra.w + gap : ra.x - gap;
    pushPt(pts, x1, y1);
    pushPt(pts, xOut, y1);
    pushPt(pts, xOut, rail);
    pushPt(pts, cx2, rail);
    pushPt(pts, cx2, ny2);
    return pts;
  }

  function loopRoute(na, nb, slot) {
    const aw = BOX_W, ah = state.pos[na].h || boxH(na), bw = BOX_W;
    const oa = state.own[na];
    const ra = ownerBBox(oa);
    const x1 = state.pos[na].x + aw / 2;
    const y1 = state.pos[na].y + ah;
    const x2 = state.pos[nb].x + bw / 2;
    const y2 = state.pos[nb].y;
    let xSide = ra.w === 0 ? state.pos[na].x - 28 : ra.x - 16;
    xSide -= (slot % 3) * 10;
    return [[x1, y1], [x1, y1 + 12], [xSide, y1 + 12], [xSide, y2 - 12], [x2, y2 - 12], [x2, y2]];
  }

  function cfgRoute(na, nb) {
    const aw = BOX_W, ah = state.pos[na].h || boxH(na), bw = BOX_W;
    const x1 = state.pos[na].x + aw / 2;
    const y1 = state.pos[na].y + ah;
    const x2 = state.pos[nb].x + bw / 2;
    const y2 = state.pos[nb].y;
    if (Math.abs(x1 - x2) <= 40) return [[x1, y1], [x2, y2]];
    const my = (y1 + y2) / 2;
    return [[x1, y1], [x1, my], [x2, my], [x2, y2]];
  }

  function edgePts(e) {
    const ed = state.edges[e];
    const na = ixOf(ed.a);
    const nb = ixOf(ed.b);
    if (na < 0 || nb < 0) return [];
    if (ed.lab === "call") return callRoute(na, nb, callSlot(e));
    if (ed.lab === "loop" || ed.lab === "next") return loopRoute(na, nb, e);
    return cfgRoute(na, nb);
  }

  function edgeVisible(e) {
    const ed = state.edges[e];
    if (ed.lab === "call") return true;
    const na = ixOf(ed.a);
    const nb = ixOf(ed.b);
    if (na < 0 || nb < 0) return false;
    const oa = state.own[na];
    return oa >= 0 && isOpen(oa) && state.own[nb] === oa;
  }

  function applyCam() {
    world.setAttribute("transform", "translate(" + state.tx + "," + state.ty + ") scale(" + state.scale + ")");
  }

  function diamondPts(x, y, w, h) {
    const cx = x + w / 2, cy = y + h / 2;
    return cx + "," + y + " " + (x + w) + "," + cy + " " + cx + "," + (y + h) + " " + x + "," + cy;
  }

  function render() {
    layout();
    applyCam();
    let html = "";
    const n = state.nodes.length;
    const fns = [];
    for (let i = 0; i < n; i++) if (isFn(state.nodes[i].label)) fns.push(i);
    for (let k = 0; k < fns.length; k++) {
      const fi = fns[k];
      const bb = ownerBBox(fi);
      if (bb.w <= 0) continue;
      const title = clip(state.nodes[fi].label, 28);
      const opened = isOpen(fi) ? 1 : 0;
      const hot = state.focus === fi || (state.focus >= 0 && state.own[state.focus] === fi);
      html += '<g class="region" data-fn="' + fi + '">';
      html += '<rect x="' + bb.x + '" y="' + bb.y + '" width="' + bb.w + '" height="' + bb.h +
        '" rx="14" fill="' + (opened ? "#19151c" : "#161318") + '" stroke="' + (hot ? "#fbbf24" : (opened ? "#881337" : "#3f3f46")) +
        '" stroke-width="' + (hot ? "2.5" : "1.5") + '"/>';
      html += '<clipPath id="clipf' + fi + '"><rect x="' + (bb.x + 10) + '" y="' + bb.y + '" width="' + Math.max(8, bb.w - 20) + '" height="28"/></clipPath>';
      html += '<rect class="bar" data-fn="' + fi + '" x="' + bb.x + '" y="' + bb.y + '" width="' + bb.w +
        '" height="' + bb.h + '" rx="14" fill="transparent" style="cursor:pointer"/>';
      html += '<text clip-path="url(#clipf' + fi + ')" x="' + (bb.x + 14) + '" y="' + (bb.y + 20) + '" fill="#fda4af" font-size="12" font-family="ui-monospace,monospace">' +
        esc(title) + (opened ? "  ▾" : "  ▸") + "</text>";
      html += "</g>";
    }
    for (let e = 0; e < state.edges.length; e++) {
      if (!edgeVisible(e)) continue;
      const pts = edgePts(e);
      if (pts.length < 2) continue;
      const ed = state.edges[e];
      const on = state.lit.has(e);
      const call = ed.lab === "call";
      let col = "#334155", w = 2, mark = "arr";
      if (call) {
        col = on ? "#c4b5fd" : "#7c3aed";
        w = on ? 3 : 2;
        mark = on ? "arr-call-lit" : "arr-call";
      } else if (on) {
        col = "#4ade80";
        w = 4;
        mark = "arr-lit";
      }
      const ps = pts.map(function (p) { return p[0] + "," + p[1]; }).join(" ");
      html += '<polyline fill="none" stroke="' + col + '" stroke-width="' + w +
        '" points="' + ps + '" marker-end="url(#' + mark + ')" pointer-events="none"/>';
      if (ed.lab && !call) {
        const mx = (pts[0][0] + pts[1][0]) / 2 + 6;
        const my = (pts[0][1] + pts[1][1]) / 2 - 6;
        html += '<text x="' + mx + '" y="' + my + '" fill="' + (on ? "#bbf7d0" : "#64748b") +
          '" font-size="11" font-family="ui-monospace,monospace" pointer-events="none">' + esc(clip(ed.lab, 16)) + "</text>";
      }
    }
    for (let i = 0; i < n; i++) {
      const oa = state.own[i];
      if (oa >= 0 && !isOpen(oa)) continue;
      const p = state.pos[i];
      const sh = state.nodes[i].shape;
      const lab = clip(state.nodes[i].label, 26);
      const fill = sh === 1 ? "#1e3a5f" : "#1e293b";
      let st = sh === 1 ? "#38bdf8" : "#64748b";
      let sw = 2;
      if (state.focus === i) {
        st = "#fbbf24";
        sw = 3;
      }
      html += '<clipPath id="clipn' + i + '"><rect x="' + (p.x + 6) + '" y="' + p.y + '" width="' + (BOX_W - 12) + '" height="' + p.h + '"/></clipPath>';
      html += '<g class="node" data-i="' + i + '" style="cursor:pointer">';
      if (sh === 1) {
        html += '<polygon points="' + diamondPts(p.x, p.y, BOX_W, p.h) + '" fill="' + fill + '" stroke="' + st + '" stroke-width="' + sw + '"/>';
      } else {
        html += '<rect x="' + p.x + '" y="' + p.y + '" width="' + BOX_W + '" height="' + p.h +
          '" rx="10" fill="' + fill + '" stroke="' + st + '" stroke-width="' + sw + '"/>';
      }
      if (noteOf(i)) {
        html += '<rect x="' + p.x + '" y="' + p.y + '" width="4" height="' + p.h + '" fill="#ca8a04" rx="1"/>';
      }
      html += '<text clip-path="url(#clipn' + i + ')" x="' + (p.x + 10) + '" y="' + (p.y + 22) + '" fill="#e2e8f0" font-size="12" font-family="ui-monospace,monospace">' +
        esc(lab) + "</text>";
      const bn = nodeBindName(i);
      if (bn) {
        const vv = state.binds[bn] || "";
        const shown = bn + " = " + (vv.length ? vv : "?");
        html += '<text clip-path="url(#clipn' + i + ')" x="' + (p.x + 10) + '" y="' + (p.y + 40) + '" fill="#fbbf24" font-size="11" font-family="ui-monospace,monospace">' +
          esc(clip(shown, 24)) + "</text>";
      }
      html += "</g>";
    }
    world.innerHTML = html;
    renderTree();
    renderBinds();
  }

  function skipTreeLab(lab) {
    return lab === "join" || lab === "(empty)";
  }

  function fnOrder() {
    const n = state.nodes.length;
    const order = [];
    const seen = {};
    const q = [];
    for (let i = 0; i < n; i++) {
      if (isFn(state.nodes[i].label) && fnName(state.nodes[i].label) === "main") q.push(i);
    }
    for (let qi = 0; qi < q.length; qi++) {
      const fi = q[qi];
      if (seen[fi]) continue;
      seen[fi] = 1;
      order.push(fi);
      for (let e = 0; e < state.edges.length; e++) {
        const ed = state.edges[e];
        if (ed.lab !== "call") continue;
        const src = ixOf(ed.a);
        if (src < 0 || state.own[src] !== fi) continue;
        const dst = ixOf(ed.b);
        if (dst >= 0 && isFn(state.nodes[dst].label) && !seen[dst]) q.push(dst);
      }
    }
    for (let i = 0; i < n; i++) {
      if (isFn(state.nodes[i].label) && !seen[i]) order.push(i);
    }
    return order;
  }

  function cfgKids(fi) {
    const kids = [];
    for (let i = 0; i < state.nodes.length; i++) {
      if (i === fi) continue;
      if (state.own[i] !== fi) continue;
      if (skipTreeLab(state.nodes[i].label)) continue;
      kids.push(i);
    }
    kids.sort(function (a, b) {
      const da = (state.depth[a] || 0) - (state.depth[b] || 0);
      if (da !== 0) return da;
      return a - b;
    });
    return kids;
  }

  function callsFrom(ni) {
    const id = state.nodes[ni].id;
    const out = [];
    const seen = {};
    for (let e = 0; e < state.edges.length; e++) {
      const ed = state.edges[e];
      if (ed.lab !== "call" || ed.a !== id) continue;
      const dst = ixOf(ed.b);
      if (dst < 0 || seen[dst]) continue;
      seen[dst] = 1;
      out.push(dst);
    }
    return out;
  }

  function nodeOnLit(i) {
    const id = state.nodes[i].id;
    for (let e = 0; e < state.edges.length; e++) {
      if (!state.lit.has(e)) continue;
      const ed = state.edges[e];
      if (ed.a === id || ed.b === id) return true;
    }
    return false;
  }

  function renderTree() {
    if (!treeEl) return;
    let html = "<h2>函数</h2>";
    if (state.err) html += '<div class="err" style="padding:0 12px">' + esc(state.err) + "</div>";
    const order = fnOrder();
    for (let o = 0; o < order.length; o++) {
      const fi = order[o];
      const opened = isOpen(fi);
      const hot = state.focus === fi || (state.focus >= 0 && state.own[state.focus] === fi);
      const nm = fnName(state.nodes[fi].label) || state.nodes[fi].label;
      html += '<div class="fn' + (opened ? " open" : "") + (hot ? " hot" : "") + '">';
      html += '<div class="fn-head" data-fn="' + fi + '"><span class="chev">' + (opened ? "▾" : "▸") +
        '</span><span class="name">' + esc(nm) + "</span></div>";
      const fnNote = noteOf(fi);
      if (fnNote) html += '<div class="note">' + esc(fnNote) + "</div>";
      if (opened) {
        const kids = cfgKids(fi);
        for (let k = 0; k < kids.length; k++) {
          const i = kids[k];
          const lab = state.nodes[i].label;
          let cls = "node-row";
          if (state.nodes[i].shape === 1) cls += " branch";
          if (nodeOnLit(i)) cls += " lit";
          if (state.focus === i) cls += " focus";
          html += '<div class="' + cls + '" data-i="' + i + '" id="tr' + i + '"><span class="lab">' + esc(lab) + "</span>";
          const bn = nodeBindName(i);
          if (bn) {
            const vv = state.binds[bn] || "?";
            html += '<span class="bind" data-k="' + esc(bn) + '">' + esc(bn) + " = " + esc(vv) + "</span>";
          }
          html += "</div>";
          const nnote = noteOf(i);
          if (nnote) html += '<div class="note">' + esc(nnote) + "</div>";
          const cals = callsFrom(i);
          for (let c = 0; c < cals.length; c++) {
            const dst = cals[c];
            const cn = fnName(state.nodes[dst].label) || state.nodes[dst].label;
            html += '<div class="call-ref" data-fn="' + dst + '">↳ ' + esc(cn) + "</div>";
          }
        }
      }
      html += "</div>";
    }
    treeEl.innerHTML = html;
  }

  function renderBinds() {
    const names = Object.keys(state.binds);
    let html = "<h2>bindings</h2>";
    if (names.length === 0) {
      html += '<div class="err">—</div>';
    }
    for (let i = 0; i < names.length; i++) {
      const k = names[i];
      const v = state.binds[k] || "?";
      html += '<div class="item" data-k="' + esc(k) + '"><span class="k">' + esc(k) +
        '</span><span class="v">' + esc(v) + "</span></div>";
    }
    bindsEl.innerHTML = html;
  }

  function panTo(i) {
    const p = state.pos[i];
    if (!p) return;
    const r = cv.getBoundingClientRect();
    state.tx = r.width / 2 - (p.x + BOX_W / 2) * state.scale;
    state.ty = r.height / 2 - (p.y + p.h / 2) * state.scale;
    applyCam();
  }

  function scrollTreeTo(i) {
    const el = document.getElementById("tr" + i);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  function selectNode(i) {
    state.focus = i;
    const oa = state.own[i];
    if (oa >= 0 && !isOpen(oa)) state.open.add(oa);
    render();
    panTo(i);
    scrollTreeTo(i);
  }

  function payloadBinds() {
    const names = Object.keys(state.binds);
    const parts = [];
    for (let i = 0; i < names.length; i++) {
      const k = names[i];
      const v = state.binds[k];
      if (v) parts.push(k + "=" + v);
    }
    return parts.join(";");
  }

  async function invoke(name, payload) {
    const X = window.__XU__;
    if (!X || !X.invoke) throw new Error("no IPC");
    return await X.invoke(name, payload || "");
  }

  async function loadGraph() {
    const raw = await invoke("graph", "");
    const g = parseDump(raw);
    state.root = g.root;
    state.err = g.err;
    state.nodes = g.nodes;
    state.edges = g.edges;
    state.binds = g.binds;
    state.open = new Set();
    state.lit = new Set();
    state.focus = -1;
    rootEl.textContent = g.err ? g.err : (g.root || "—");
    render();
  }

  async function runSim() {
    const raw = await invoke("sim", payloadBinds());
    const lit = new Set();
    String(raw || "").split(",").forEach(function (s) {
      if (s.length) lit.add(+s);
    });
    state.lit = lit;
    render();
  }

  function fit() {
    state.tx = 32;
    state.ty = 16;
    state.scale = 1;
    applyCam();
  }

  function worldXY(ev) {
    const r = cv.getBoundingClientRect();
    return {
      x: (ev.clientX - r.left - state.tx) / state.scale,
      y: (ev.clientY - r.top - state.ty) / state.scale
    };
  }

  function inBox(wx, wy, x, y, w, h) {
    return wx >= x && wy >= y && wx <= x + w && wy <= y + h;
  }

  function hitAt(wx, wy) {
    const n = state.nodes.length;
    for (let i = n - 1; i >= 0; i--) {
      const oa = state.own[i];
      if (oa >= 0 && !isOpen(oa)) continue;
      const p = state.pos[i];
      if (!p) continue;
      if (inBox(wx, wy, p.x, p.y, BOX_W, p.h)) return { kind: "node", i: i };
    }
    const fns = [];
    for (let i = 0; i < n; i++) {
      if (isFn(state.nodes[i].label)) fns.push(i);
    }
    for (let k = fns.length - 1; k >= 0; k--) {
      const fi = fns[k];
      const bb = ownerBBox(fi);
      if (bb.w <= 0) continue;
      if (!inBox(wx, wy, bb.x, bb.y, bb.w, bb.h)) continue;
      if (!isOpen(fi) || wy <= bb.y + 34) return { kind: "fn", i: fi };
    }
    return null;
  }

  function onCanvasTap(ev) {
    const w = worldXY(ev);
    const hit = hitAt(w.x, w.y);
    if (!hit) return;
    if (hit.kind === "node") {
      selectNode(hit.i);
      const name = nodeBindName(hit.i);
      if (name) openPrompt(name);
      return;
    }
    if (hit.kind === "fn") {
      toggleFn(hit.i);
    }
  }

  let dragging = false;
  let moved = false;
  let lastX = 0, lastY = 0;
  let promptName = "";

  cv.addEventListener("mousedown", function (ev) {
    if (ev.button !== 0) return;
    dragging = true;
    moved = false;
    lastX = ev.clientX;
    lastY = ev.clientY;
  });
  window.addEventListener("mousemove", function (ev) {
    if (!dragging) return;
    const dx = ev.clientX - lastX;
    const dy = ev.clientY - lastY;
    if (!moved) {
      if (Math.abs(dx) + Math.abs(dy) < 8) return;
      moved = true;
      cv.classList.add("drag");
    }
    lastX = ev.clientX;
    lastY = ev.clientY;
    state.tx += dx;
    state.ty += dy;
    applyCam();
  });
  window.addEventListener("mouseup", function (ev) {
    if (!dragging) return;
    dragging = false;
    cv.classList.remove("drag");
    if (moved) return;
    onCanvasTap(ev);
  });
  cv.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    const r = cv.getBoundingClientRect();
    const cx = ev.clientX - r.left;
    const cy = ev.clientY - r.top;
    if (ev.ctrlKey || ev.metaKey) {
      const wx = (cx - state.tx) / state.scale;
      const wy = (cy - state.ty) / state.scale;
      const factor = ev.deltaY < 0 ? 1.08 : 0.92;
      const next = Math.min(2.6, Math.max(0.35, state.scale * factor));
      state.scale = next;
      state.tx = cx - wx * state.scale;
      state.ty = cy - wy * state.scale;
    } else {
      state.tx -= ev.deltaX;
      state.ty -= ev.deltaY;
    }
    applyCam();
  }, { passive: false });

  document.getElementById("side").addEventListener("click", function (ev) {
    const bind = ev.target.closest && ev.target.closest("[data-k]");
    const row = ev.target.closest && ev.target.closest("[data-i]");
    const fn = ev.target.closest && ev.target.closest("[data-fn]");
    if (bind) {
      openPrompt(bind.getAttribute("data-k"));
      return;
    }
    if (row) {
      selectNode(+row.getAttribute("data-i"));
      return;
    }
    if (fn) {
      const fi = +fn.getAttribute("data-fn");
      if (ev.target.closest && ev.target.closest(".call-ref")) {
        state.focus = fi;
        state.open.add(fi);
        render();
        panTo(fi);
        return;
      }
      toggleFn(fi);
    }
  });

  const dlg = document.getElementById("dlg");
  const dlgIn = document.getElementById("dlg_in");
  const dlgLab = document.getElementById("dlg_lab");

  function openPrompt(name) {
    promptName = name;
    dlgLab.textContent = name;
    dlgIn.value = state.binds[name] || "";
    dlg.hidden = false;
    dlgIn.focus();
    dlgIn.select();
  }

  function closePrompt() {
    dlg.hidden = true;
    promptName = "";
  }

  async function commitPrompt() {
    if (!promptName) return closePrompt();
    state.binds[promptName] = dlgIn.value;
    closePrompt();
    render();
    try { await runSim(); } catch (e) { state.err = String(e && e.message ? e.message : e); renderBinds(); }
  }

  document.getElementById("dlg_ok").onclick = commitPrompt;
  document.getElementById("dlg_cancel").onclick = closePrompt;
  dlgIn.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") commitPrompt();
    if (ev.key === "Escape") closePrompt();
  });

  document.getElementById("btn_sim").onclick = function () {
    runSim().catch(function (e) {
      state.err = String(e && e.message ? e.message : e);
      renderBinds();
    });
  };
  document.getElementById("btn_fit").onclick = fit;
  document.getElementById("btn_open").onclick = function () {
    const next = new Set();
    for (let i = 0; i < state.nodes.length; i++) {
      if (isFn(state.nodes[i].label)) next.add(i);
    }
    state.open = next;
    render();
  };
  document.getElementById("btn_close").onclick = function () {
    state.open = new Set();
    render();
  };

  function boot() {
    loadGraph().catch(function (e) {
      rootEl.textContent = String(e && e.message ? e.message : e);
    });
  }
  if (window.__XU__ && window.__XU__.invoke) boot();
  else setTimeout(boot, 200);
})();
