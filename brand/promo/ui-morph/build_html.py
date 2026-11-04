#!/usr/bin/env python3
"""Assemble single-file XU UI morph HTML from embeds."""
import json
from pathlib import Path

E = json.loads(Path("/tmp/xu-ui/embed.json").read_text())
M = E["meta"]
F = E["fonts"]

html = rf"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>XU UI Morph</title>
<style>
@font-face {{
  font-family: 'Geist';
  src: url(data:font/woff2;base64,{F['Regular']}) format('woff2');
  font-weight: 400; font-style: normal;
}}
@font-face {{
  font-family: 'Geist';
  src: url(data:font/woff2;base64,{F['Medium']}) format('woff2');
  font-weight: 500; font-style: normal;
}}
@font-face {{
  font-family: 'Geist';
  src: url(data:font/woff2;base64,{F['SemiBold']}) format('woff2');
  font-weight: 600; font-style: normal;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  width: 1440px; height: 1440px; overflow: hidden;
  background: #EDEBE6;
  font-family: 'Geist', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}}
#stage {{
  position: absolute; left: 0; top: 0; width: 1440px; height: 1440px;
  transform-origin: 50% 50%;
}}
#shape {{
  position: absolute;
  left: 50%; top: 50%;
  transform: translate(-50%, -50%);
  overflow: hidden;
  background: #0B0A0F;
  color: #FAF9F6;
  display: flex; align-items: center; justify-content: center;
  /* never will-change — camera scales the stage */
}}
#content {{
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  pointer-events: none;
}}
#content .layer {{
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  flex-direction: column;
}}
#cursor {{
  position: absolute; width: 28px; height: 28px; margin-left: -4px; margin-top: -2px;
  pointer-events: none; z-index: 50;
}}
#cursor svg {{ display: block; filter: drop-shadow(0 1px 1px rgba(0,0,0,.25)); }}
#hit {{ display: none; }}
</style>
</head>
<body>
<div id="stage">
  <div id="shape"><div id="content"></div></div>
</div>
<div id="cursor">
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
    <path d="M5.5 3.5 L5.5 18.5 L9.2 15.2 L12.2 21.2 L14.4 20.2 L11.3 14.1 L16.5 14.1 Z"
      fill="#0B0A0F" stroke="#FAF9F6" stroke-width="1.2" stroke-linejoin="round"/>
  </svg>
</div>
<script>
const BPM = {M['bpm']};
const PERIOD = {M['period']};
const DURATION = {M['duration']};
const RED = '#FF385C';
const BLACK = '#0B0A0F';
const WHITE = '#FAF9F6';
const CANVAS = '#E8E6E1';
const LOGO = 'data:image/png;base64,{E['logo']}';

const SFX = {{
  click: 'data:audio/wav;base64,{E['sfx']['click']}',
  check: 'data:audio/wav;base64,{E['sfx']['check']}',
  toggle: 'data:audio/wav;base64,{E['sfx']['toggle']}',
  whoosh: 'data:audio/wav;base64,{E['sfx']['whoosh']}',
  key: 'data:audio/wav;base64,{E['sfx']['key']}',
  scrub: 'data:audio/wav;base64,{E['sfx']['scrub']}',
  toast: 'data:audio/wav;base64,{E['sfx']['toast']}',
}};
const BED = 'data:audio/mpeg;base64,{E['bed']}';

/* ---- closed-form springs (pure function of time) ---- */
function springStep(t, w = 16, z = 0.84) {{
  if (t <= 0) return 0;
  const zz = Math.min(0.999, z);
  const wd = w * Math.sqrt(Math.max(1e-6, 1 - zz * zz));
  return 1 - Math.exp(-zz * w * t) * (Math.cos(wd * t) + (zz * w / wd) * Math.sin(wd * t));
}}

/** changes: array of {{t, v}} absolute targets over time; first is initial at t=-inf */
function springTrack(t, changes, w = 16, z = 0.84) {{
  if (!changes.length) return 0;
  let x = changes[0].v;
  for (let i = 1; i < changes.length; i++) {{
    const d = changes[i].v - changes[i - 1].v;
    x += d * springStep(t - changes[i].t, w, z);
  }}
  return x;
}}

function lerp(a, b, u) {{ return a + (b - a) * u; }}
function clamp(x, a, b) {{ return Math.max(a, Math.min(b, x)); }}
function smooth(u) {{ u = clamp(u, 0, 1); return u * u * (3 - 2 * u); }}

function beat(i) {{ return i * PERIOD; }}

/* Content enter/exit with blur — separate timing so text never overlaps */
function contentAlpha(t, enterAt, exitAt, inDur = 0.14, outDur = 0.12) {{
  // Stagger: previous begins exiting slightly before the beat; new enters on the beat.
  const enter = enterAt;
  const exit = exitAt == null ? null : exitAt - 0.05;
  let a = 0;
  if (t >= enter) a = springStep(t - enter, 22, 0.9);
  else a = 0;
  if (exit != null && t >= exit) a *= 1 - springStep(t - exit, 28, 0.92);
  // hard cut residual
  if (exit != null && t >= exitAt + 0.12) a = 0;
  if (t < enter) a = 0;
  return clamp(a, 0, 1);
}}
function contentBlur(t, enterAt, exitAt) {{
  let b = 0;
  if (t >= enterAt && t < enterAt + 0.16) b = (1 - (t - enterAt) / 0.16) * 7;
  if (exitAt != null) {{
    const ex = exitAt - 0.05;
    if (t >= ex && t < ex + 0.14) b = Math.max(b, ((t - ex) / 0.14) * 7);
  }}
  return b;
}}

/* ---- timeline targets (beat-locked) ---- */
/*
  0 Logo
  1 Logo→Button (click)
  2 Button→Loader
  3 Loader spin
  4 Loader→Check
  5 Check
  6 Check→Island
  7 Island expand
  8 Island→Player
  9 Play/Pause
 10 Scrub progress
 11 Volume stretch past max
 12 Release settle
 13 →Toggle
 14 Toggle ON
 15 →Liquid tabs
 16 Tab slide
 17 →Chart
 18 Chart draw
 19 Tooltip
 20 →⌘K
 21 Type
 22 Enter
 23 →Toast
 24 Toast
 25 →Logo
 26 Logo form / cursor home
 27 settle
 28 = 0
*/

const Wchg = [
  {{t: -1, v: 280}}, // logo + wordmark
  {{t: beat(1), v: 300}}, // Install XU
  {{t: beat(2), v: 128}}, // loader
  {{t: beat(4), v: 128}}, // check
  {{t: beat(6), v: 560}}, // island
  {{t: beat(7), v: 760}},
  {{t: beat(8), v: 680}}, // player
  {{t: beat(11), v: 600}}, // volume
  {{t: beat(12), v: 440}},
  {{t: beat(13), v: 128}}, // toggle
  {{t: beat(15), v: 520}}, // tabs CLI/HTTP/UI
  {{t: beat(17), v: 820}}, // chart
  {{t: beat(20), v: 720}}, // cmdk
  {{t: beat(23), v: 460}}, // toast
  {{t: beat(25), v: 280}}, // logo
];
const Hchg = [
  {{t: -1, v: 280}},
  {{t: beat(1), v: 96}},
  {{t: beat(2), v: 128}},
  {{t: beat(4), v: 128}},
  {{t: beat(6), v: 88}},
  {{t: beat(7), v: 100}},
  {{t: beat(8), v: 260}},
  {{t: beat(11), v: 76}},
  {{t: beat(13), v: 68}},
  {{t: beat(15), v: 76}},
  {{t: beat(17), v: 500}},
  {{t: beat(20), v: 380}},
  {{t: beat(23), v: 92}},
  {{t: beat(25), v: 280}},
];
const Rchg = [ // corner radius
  {{t: -1, v: 40}},
  {{t: beat(1), v: 48}}, // pill button
  {{t: beat(2), v: 64}}, // circle loader
  {{t: beat(4), v: 64}},
  {{t: beat(6), v: 44}}, // island
  {{t: beat(8), v: 32}},
  {{t: beat(11), v: 38}},
  {{t: beat(13), v: 34}},
  {{t: beat(15), v: 38}},
  {{t: beat(17), v: 28}},
  {{t: beat(20), v: 22}},
  {{t: beat(23), v: 18}},
  {{t: beat(25), v: 40}},
];
const BgChg = [ // 0 black, 1 white, 2 red
  {{t: -1, v: 0}},
  {{t: beat(1), v: 0}},
  {{t: beat(2), v: 0}},
  {{t: beat(4), v: 2}}, // check on red
  {{t: beat(6), v: 0}},
  {{t: beat(14), v: 0}},
  {{t: beat(23), v: 0}},
  {{t: beat(25), v: 0}},
];

function bgColor(v) {{
  if (v < 1) {{
    const u = v;
    // black→white
    if (u <= 0) return BLACK;
    // treat 0..1 as black-white, 1..2 white-red? simpler discrete morph via mix
  }}
  const black = [11, 10, 15], white = [250, 249, 246], red = [255, 56, 92];
  let c;
  if (v <= 1) {{
    const u = clamp(v, 0, 1);
    c = black.map((a, i) => Math.round(lerp(a, white[i], u)));
  }} else {{
    const u = clamp(v - 1, 0, 1);
    c = white.map((a, i) => Math.round(lerp(a, red[i], u)));
  }}
  // remap: 0 black, 2 red directly for check
  if (v >= 1.5) {{
    const u = clamp((v - 1), 0, 1);
    c = black.map((a, i) => Math.round(lerp(a, red[i], u)));
  }}
  return `rgb(${{c[0]}},${{c[1]}},${{c[2]}})`;
}}

/* Dual-edge tab indicator / toggle knob */
function dualEdge(t, leftChanges, rightChanges, w = 18, z = 0.8) {{
  return {{
    L: springTrack(t, leftChanges, w, z),
    R: springTrack(t, rightChanges, w * 0.72, z * 0.95), // leading edge faster stretch
  }};
}}

/* Cursor path — closed loop: end matches start in position AND velocity */
function cursorState(t) {{
  // key poses at beats (x,y) in stage space, center 720,720
  const poses = [
    {{t: beat(0), x: 520, y: 900}},
    {{t: beat(1), x: 720, y: 760}}, // click logo/button
    {{t: beat(2), x: 720, y: 760}},
    {{t: beat(5), x: 820, y: 700}},
    {{t: beat(7), x: 900, y: 720}},
    {{t: beat(9), x: 640, y: 780}}, // play
    {{t: beat(10), x: 560, y: 820}}, // scrub start
    {{t: beat(11), x: 980, y: 820}}, // drag past max
    {{t: beat(12), x: 900, y: 820}},
    {{t: beat(14), x: 760, y: 720}}, // toggle
    {{t: beat(16), x: 880, y: 720}}, // tab
    {{t: beat(19), x: 860, y: 620}}, // tooltip
    {{t: beat(21), x: 700, y: 700}}, // type
    {{t: beat(22), x: 980, y: 780}}, // enter
    {{t: beat(24), x: 900, y: 640}},
    {{t: beat(26), x: 560, y: 860}},
    {{t: beat(28), x: 520, y: 900}}, // = start
  ];
  // piecewise spring toward each pose
  const xCh = poses.map(p => ({{t: p.t, v: p.x}}));
  const yCh = poses.map(p => ({{t: p.t, v: p.y}}));
  // down press on click beats
  const pressBeats = [1, 9, 14, 22];
  let press = 0;
  for (const b of pressBeats) {{
    const dt = t - beat(b);
    if (dt >= 0 && dt < 0.16) press = Math.max(press, Math.sin((dt / 0.16) * Math.PI));
  }}
  // drag flag for scrub/volume
  const dragging = (t >= beat(10) && t < beat(12.15));
  return {{
    x: springTrack(t, xCh, 12, 0.88),
    y: springTrack(t, yCh, 12, 0.88),
    press,
    dragging,
  }};
}}

/* Camera zoom so active state fills frame */
function cameraScale(t) {{
  const ch = [
    {{t: -1, v: 1.42}}, // logo fills
    {{t: beat(1), v: 1.38}},
    {{t: beat(2), v: 1.75}},
    {{t: beat(6), v: 1.22}},
    {{t: beat(8), v: 1.12}},
    {{t: beat(11), v: 1.28}},
    {{t: beat(13), v: 1.7}},
    {{t: beat(15), v: 1.22}},
    {{t: beat(17), v: 1.02}},
    {{t: beat(20), v: 1.08}},
    {{t: beat(23), v: 1.32}},
    {{t: beat(25), v: 1.42}},
  ];
  return springTrack(t, ch, 11, 0.88);
}}

/* Progress / volume value from direct manipulation while held */
function scrubValue(t) {{
  const start = beat(10);
  const end = beat(11);
  const release = beat(12);
  if (t < start) return 0.18;
  const cur = cursorState(t);
  // map cursor x 560..980 → 0..1.35 (past max)
  const raw = clamp((cur.x - 560) / (980 - 560), 0, 1.35);
  if (t <= end) return raw; // direct while dragging into volume morph
  if (t < release) {{
    // still held stretching
    return raw;
  }}
  // release: spring back from wherever it was at release toward 0.72
  const atRel = clamp((cursorState(release).x - 560) / 420, 0, 1.35);
  const u = springStep(t - release, 14, 0.82);
  return lerp(atRel, 0.72, u);
}}

function toggleOn(t) {{
  return t >= beat(14) - 0.001;
}}

function tabIndex(t) {{
  if (t < beat(16)) return 0;
  if (t < beat(17)) return 1;
  return 2;
}}

function chartProgress(t) {{
  return clamp(springStep(t - beat(17), 6, 0.92), 0, 1);
}}

function typeText(t) {{
  const full = 'native';
  if (t < beat(21)) return '';
  const n = Math.min(full.length, Math.floor((t - beat(21)) / (PERIOD / 6.5) + 0.001));
  return full.slice(0, n);
}}

function playOn(t) {{
  return t >= beat(9) - 0.001;
}}

const shapeEl = document.getElementById('shape');
const contentEl = document.getElementById('content');
const stageEl = document.getElementById('stage');
const cursorEl = document.getElementById('cursor');

function modeAt(t) {{
  if (t < beat(1)) return 'logo';
  if (t < beat(2)) return 'button';
  if (t < beat(4)) return 'loader';
  if (t < beat(6)) return 'check';
  if (t < beat(8)) return 'island';
  if (t < beat(11)) return 'player';
  if (t < beat(13)) return 'volume';
  if (t < beat(15)) return 'toggle';
  if (t < beat(17)) return 'tabs';
  if (t < beat(20)) return 'chart';
  if (t < beat(23)) return 'cmdk';
  if (t < beat(25)) return 'toast';
  return 'logo';
}}

function renderContent(t) {{
  const parts = [];

  // LOGO
  {{
    const a = contentAlpha(t, -1, beat(1));
    const a2 = contentAlpha(t, beat(25), null);
    const alpha = Math.max(a, a2);
    const blur = Math.max(contentBlur(t, -1, beat(1)), contentBlur(t, beat(25), null));
    if (alpha > 0.01) {{
      parts.push(`<div class="layer" style="opacity:${{alpha}};filter:blur(${{blur}}px);gap:14px">
        <img src="${{LOGO}}" width="96" height="96" alt="XU" style="display:block;border-radius:22px"/>
        <div style="font-weight:700;font-size:42px;letter-spacing:-0.04em;color:${{WHITE}}">XU</div>
      </div>`);
    }}
  }}

  // BUTTON
  {{
    const a = contentAlpha(t, beat(1), beat(2));
    const blur = contentBlur(t, beat(1), beat(2));
    if (a > 0.01) {{
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);color:${{WHITE}};font-weight:600;font-size:28px;letter-spacing:0.01em">Install XU</div>`);
    }}
  }}

  // LOADER
  {{
    const a = contentAlpha(t, beat(2), beat(4));
    const blur = contentBlur(t, beat(2), beat(4));
    if (a > 0.01) {{
      const rot = ((t - beat(2)) / PERIOD) * 360;
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px)">
        <div style="width:54px;height:54px;border-radius:50%;border:4px solid rgba(250,249,246,0.2);border-top-color:${{RED}};transform:rotate(${{rot}}deg)"></div>
      </div>`);
    }}
  }}

  // CHECK
  {{
    const a = contentAlpha(t, beat(4), beat(6));
    const blur = contentBlur(t, beat(4), beat(6));
    if (a > 0.01) {{
      const draw = springStep(t - beat(4), 18, 0.85);
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px)">
        <svg width="64" height="64" viewBox="0 0 64 64">
          <path d="M14 34 L28 48 L50 18" fill="none" stroke="${{WHITE}}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"
            stroke-dasharray="80" stroke-dashoffset="${{80 * (1 - draw)}}"/>
        </svg>
      </div>`);
    }}
  }}

  // ISLAND
  {{
    const a = contentAlpha(t, beat(6), beat(8));
    const blur = contentBlur(t, beat(6), beat(8));
    if (a > 0.01) {{
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);flex-direction:row;gap:16px;padding:0 28px;justify-content:flex-start">
        <div style="width:14px;height:14px;border-radius:50%;background:${{RED}};margin-left:12px"></div>
        <div style="color:${{WHITE}};font-size:20px;font-weight:500;letter-spacing:0.01em">Zero GC · Inferred Ownership</div>
      </div>`);
    }}
  }}

  // PLAYER
  {{
    const a = contentAlpha(t, beat(8), beat(11));
    const blur = contentBlur(t, beat(8), beat(11));
    if (a > 0.01) {{
      const playing = playOn(t);
      const prog = scrubValue(t);
      const p = clamp(prog, 0, 1);
      // play/pause morph paths
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);padding:36px;align-items:stretch;justify-content:space-between">
        <div style="display:flex;gap:16px;align-items:center">
          <img src="${{LOGO}}" width="64" height="64" style="border-radius:14px;display:block"/>
          <div>
            <div style="font-weight:600;font-size:24px;color:${{WHITE}}">Clear intent.</div>
            <div style="font-size:16px;color:rgba(250,249,246,0.55);margin-top:4px">Native code. · AOT</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:20px;margin-top:18px">
          <svg width="36" height="36" viewBox="0 0 36 36">
            ${{playing
              ? `<rect x="10" y="8" width="5" height="20" rx="1.5" fill="${{WHITE}}"/><rect x="21" y="8" width="5" height="20" rx="1.5" fill="${{WHITE}}"/>`
              : `<path d="M12 8 L28 18 L12 28 Z" fill="${{WHITE}}"/>`}}
          </svg>
          <div style="flex:1;height:6px;border-radius:3px;background:rgba(250,249,246,0.15);position:relative">
            <div style="position:absolute;left:0;top:0;bottom:0;width:${{p * 100}}%;background:${{RED}};border-radius:3px"></div>
            <div style="position:absolute;top:50%;left:${{p * 100}}%;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;background:${{WHITE}}"></div>
          </div>
        </div>
      </div>`);
    }}
  }}

  // VOLUME
  {{
    const a = contentAlpha(t, beat(11), beat(13));
    const blur = contentBlur(t, beat(11), beat(13));
    if (a > 0.01) {{
      const v = scrubValue(t);
      const fill = clamp(v, 0, 1);
      const stretch = Math.max(0, v - 1); // past max
      const barW = 100 + stretch * 40;
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);padding:0 28px;flex-direction:row;gap:18px">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="${{WHITE}}"><path d="M4 9v6h4l5 4V5L8 9H4zm11.5 3a3.5 3.5 0 0 0-1.5-2.9v5.8a3.5 3.5 0 0 0 1.5-2.9z"/></svg>
        <div style="flex:1;height:10px;border-radius:5px;background:rgba(250,249,246,0.15);transform:scaleX(${{barW / 100}});transform-origin:left center;position:relative">
          <div style="height:100%;width:${{fill * 100}}%;background:${{RED}};border-radius:5px"></div>
          <div style="position:absolute;top:50%;left:${{Math.min(fill,1) * 100}}%;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:${{WHITE}}"></div>
        </div>
      </div>`);
    }}
  }}

  // TOGGLE
  {{
    const a = contentAlpha(t, beat(13), beat(15));
    const blur = contentBlur(t, beat(13), beat(15));
    if (a > 0.01) {{
      const on = toggleOn(t);
      // dual-edge knob: left/right different springs
      const knob = dualEdge(t,
        [{{t: -1, v: 6}}, {{t: beat(14) - 0.02, v: 52}}],
        [{{t: -1, v: 42}}, {{t: beat(14) - 0.02, v: 88}}],
        22, 0.78
      );
      const trackBg = on ? RED : 'rgba(250,249,246,0.2)';
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px)">
        <div style="width:96px;height:52px;border-radius:26px;background:${{trackBg}};position:relative">
          <div style="position:absolute;top:6px;left:${{knob.L}}px;width:${{Math.max(8, knob.R - knob.L)}}px;height:40px;border-radius:20px;background:${{WHITE}}"></div>
        </div>
      </div>`);
    }}
  }}

  // TABS
  {{
    const a = contentAlpha(t, beat(15), beat(17));
    const blur = contentBlur(t, beat(15), beat(17));
    if (a > 0.01) {{
      const labels = ['CLI', 'HTTP', 'UI'];
      const idx = tabIndex(t);
      // liquid indicator edges
      const slot = 140;
      const base = 24;
      const Lch = [{{t: -1, v: base}}, {{t: beat(16), v: base + slot}}];
      const Rch = [{{t: -1, v: base + 110}}, {{t: beat(16), v: base + slot + 110}}];
      // leading edge uses faster spring on the right when moving right
      const edges = dualEdge(t, Lch, Rch, 18, 0.8);
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);padding:0 20px">
        <div style="position:relative;width:100%;height:100%;display:flex;align-items:center">
          <div style="position:absolute;top:12px;left:${{edges.L}}px;width:${{Math.max(20, edges.R - edges.L)}}px;height:48px;border-radius:14px;background:${{RED}}"></div>
          <div style="position:relative;display:flex;width:100%;justify-content:space-around;font-weight:500;font-size:22px">
            ${{labels.map((lb, i) => `<span style="color:${{i === idx ? WHITE : 'rgba(250,249,246,0.45)'}};padding:10px 18px">${{lb}}</span>`).join('')}}
          </div>
        </div>
      </div>`);
    }}
  }}

  // CHART
  {{
    const a = contentAlpha(t, beat(17), beat(20));
    const blur = contentBlur(t, beat(17), beat(20));
    if (a > 0.01) {{
      const p = chartProgress(t);
      const pts = [0.2,0.35,0.28,0.55,0.48,0.72,0.66,0.9];
      const w = 640, h = 280, pad = 40;
      let d = '';
      const n = pts.length;
      const shown = Math.max(2, Math.floor(1 + (n - 1) * p));
      for (let i = 0; i < shown; i++) {{
        const x = pad + (w - pad * 2) * (i / (n - 1));
        const y = pad + (h - pad * 2) * (1 - pts[i]);
        d += (i === 0 ? `M ${{x}} ${{y}}` : ` L ${{x}} ${{y}}`);
      }}
      // tooltip on beat 19
      const tipA = contentAlpha(t, beat(19), beat(20));
      const tipX = pad + (w - pad * 2) * (6 / (n - 1));
      const tipY = pad + (h - pad * 2) * (1 - pts[6]);
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);padding:28px;align-items:stretch">
        <div style="display:flex;justify-content:space-between;align-items:baseline;width:100%;margin-bottom:8px">
          <div style="font-weight:600;font-size:22px;color:${{WHITE}}">Benchmarks</div>
          <div style="font-size:14px;color:rgba(250,249,246,0.45)">72 workloads · 6 platforms</div>
        </div>
        <svg width="100%" height="78%" viewBox="0 0 ${{w}} ${{h}}" preserveAspectRatio="none">
          <path d="${{d}}" fill="none" stroke="${{RED}}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
          ${{tipA > 0.01 ? `<g opacity="${{tipA}}">
            <circle cx="${{tipX}}" cy="${{tipY}}" r="6" fill="${{WHITE}}"/>
            <rect x="${{tipX + 12}}" y="${{tipY - 42}}" width="128" height="44" rx="10" fill="${{WHITE}}"/>
            <text x="${{tipX + 22}}" y="${{tipY - 16}}" fill="${{BLACK}}" font-size="15" font-family="Geist" font-weight="600">XU · vs Go/Rust</text>
          </g>` : ''}}
        </svg>
      </div>`);
    }}
  }}

  // CMD+K
  {{
    const a = contentAlpha(t, beat(20), beat(23));
    const blur = contentBlur(t, beat(20), beat(23));
    if (a > 0.01) {{
      const q = typeText(t);
      const catalog = [
        {{t: 'Install XU', k: 'install'}},
        {{t: 'Native UI & WebView', k: 'native ui webview'}},
        {{t: 'Ownership & lifetimes', k: 'ownership lifetimes'}},
        {{t: 'Coroutines & channels', k: 'coroutines channels'}},
        {{t: 'WebAssembly AOT', k: 'webassembly wasm aot'}},
      ];
      const items = !q ? catalog : catalog.filter(s =>
        s.k.split(' ').some(w => w.startsWith(q)) ||
        s.t.toLowerCase().split(/\\s+/).some(w => w.startsWith(q))
      );
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);padding:22px;align-items:stretch;justify-content:flex-start">
        <div style="display:flex;align-items:center;gap:12px;border-bottom:1px solid rgba(250,249,246,0.12);padding-bottom:14px">
          <span style="font-size:22px;color:rgba(250,249,246,0.45)">⌘K</span>
          <span style="font-size:24px;font-weight:500;color:${{WHITE}}">${{q}}<span style="opacity:0.35">|</span></span>
        </div>
        <div style="margin-top:12px;display:flex;flex-direction:column;gap:6px;width:100%">
          ${{items.slice(0, 4).map((it, i) => `<div style="padding:12px 14px;border-radius:12px;background:${{i===0?RED:'transparent'}};color:${{WHITE}};font-size:20px;font-weight:500">${{it.t}}</div>`).join('')}}
        </div>
      </div>`);
    }}
  }}

  // TOAST
  {{
    const a = contentAlpha(t, beat(23), beat(25));
    const blur = contentBlur(t, beat(23), beat(25));
    if (a > 0.01) {{
      parts.push(`<div class="layer" style="opacity:${{a}};filter:blur(${{blur}}px);flex-direction:row;gap:14px;padding:0 22px">
        <div style="width:22px;height:22px;border-radius:50%;background:${{RED}};display:flex;align-items:center;justify-content:center">
          <svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 6 L5 9 L10 3" stroke="${{WHITE}}" stroke-width="2" fill="none" stroke-linecap="round"/></svg>
        </div>
        <div style="color:${{WHITE}};font-weight:500;font-size:20px">SDK 0.11.2 ready</div>
      </div>`);
    }}
  }}

  contentEl.innerHTML = parts.join('');
}}

function seek(t) {{
  // wrap for safety
  t = ((t % DURATION) + DURATION) % DURATION;
  // near end, blend toward t=0 values already encoded via beat(28)=beat(0) poses

  const w = springTrack(t, Wchg, 14, 0.86);
  const h = springTrack(t, Hchg, 14, 0.86);
  const r = springTrack(t, Rchg, 14, 0.86);
  const bgv = springTrack(t, [
    {{t: -1, v: 0}},
    {{t: beat(4), v: 2}},
    {{t: beat(6), v: 0}},
  ], 16, 0.88);

  shapeEl.style.width = w + 'px';
  shapeEl.style.height = h + 'px';
  shapeEl.style.borderRadius = r + 'px';
  // check uses red fill
  if (t >= beat(4) && t < beat(6)) {{
    const u = springTrack(t, [{{t: -1, v: 0}}, {{t: beat(4), v: 1}}, {{t: beat(6), v: 0}}], 16, 0.88);
    const black = [11,10,15], red = [255,56,92];
    const c = black.map((a,i)=>Math.round(lerp(a, red[i], clamp(u,0,1))));
    shapeEl.style.background = `rgb(${{c[0]}},${{c[1]}},${{c[2]}})`;
  }} else if (t >= beat(23) && t < beat(25)) {{
    shapeEl.style.background = BLACK;
  }} else {{
    shapeEl.style.background = BLACK;
  }}
  shapeEl.style.color = WHITE;

  const cam = cameraScale(t);
  stageEl.style.transform = `scale(${{cam}})`;

  renderContent(t);

  const cur = cursorState(t);
  cursorEl.style.left = cur.x + 'px';
  cursorEl.style.top = cur.y + 'px';
  cursorEl.style.transform = `scale(${{1 - cur.press * 0.12}})`;
  cursorEl.style.opacity = '1';

  return {{ mode: modeAt(t), w, h, cam, t }};
}}

// Expose for Playwright
window.seek = seek;
window.DURATION = DURATION;
window.PERIOD = PERIOD;
window.BPM = BPM;
window.BEAT = beat;

// Audio helpers for optional realtime preview (render mixes offline)
window.SFX = SFX;
window.BED = BED;
window.META = {{
  track: {json.dumps(M['track'])},
  artist: {json.dumps(M['artist'])},
  bpm: BPM,
  period: PERIOD,
  duration: DURATION,
}};

// Initial frame
seek(0);
</script>
</body>
</html>
"""

Path("/tmp/xu-ui/index.html").write_text(html)
print("wrote index.html", Path("/tmp/xu-ui/index.html").stat().st_size)
