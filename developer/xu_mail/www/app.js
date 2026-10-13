const $ = (id) => document.getElementById(id);

function user() {
  return ($("user").value || "ada").trim().toLowerCase();
}

function qs(extra) {
  const p = new URLSearchParams(extra || {});
  p.set("user", user());
  return p.toString();
}

async function api(path, opts) {
  const sep = path.includes("?") ? "&" : "?";
  const r = await fetch(path + sep + qs(), opts);
  const data = await r.json().catch(() => ({ ok: false, error: "bad json" }));
  if (!r.ok || data.ok === false) {
    throw new Error(data.error || r.statusText || "request failed");
  }
  return data;
}

async function post(path, fields) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(fields),
  });
}

function flash(msg, ok) {
  const el = $("flash");
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.className = "card " + (ok ? "ok" : "err");
  el.textContent = msg;
}

function go(hash) {
  location.hash = hash;
}

function hashParts() {
  const raw = (location.hash || "#/inbox").replace(/^#/, "");
  const [path, query] = raw.split("?");
  const segs = path.replace(/^\//, "").split("/");
  const q = new URLSearchParams(query || "");
  return { segs, q, path: "/" + segs.join("/") };
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&#34;", "'": "&#39;" }[c]
  ));
}

async function refreshNav(active, group) {
  const meta = await api("/api/meta");
  $("who").textContent = "邮箱 " + meta.user + "@" + meta.domain;
  if ($("user").value !== meta.user) $("user").value = meta.user;
  const folders = [
    ["inbox", "收件箱", meta.inbox, ""],
    ["sent", "已发送", meta.sent, ""],
    ["spam", "垃圾箱", meta.spam, " spam"],
    ["compose", "写邮件", null, ""],
    ["contacts", "联系人", null, ""],
    ["groups", "分组", null, ""],
    ["rules", "过滤规则", null, ""],
  ];
  $("nav-folders").innerHTML = folders.map(([id, label, n, badge]) => {
    const on = active === id && !group ? " on" : "";
    const count = n == null ? "" : ` <span class="badge${badge}">${n}</span>`;
    return `<a class="${on.trim()}" href="#/${id}">${label}${count}</a>`;
  }).join("");
  $("nav-groups").innerHTML = (meta.groups || []).map((g) => {
    const on = group === g ? " on" : "";
    return `<a class="${on.trim()}" href="#/inbox?group=${encodeURIComponent(g)}">${esc(g)}</a>`;
  }).join("");
}

function renderList(title, mails) {
  $("title").textContent = title;
  $("actions").innerHTML = "";
  if (!mails.length) {
    $("view").innerHTML = `<div class="card"><p class="muted">没有邮件</p></div>`;
    return;
  }
  const rows = mails.map((m) => {
    const sub = m.subject || "(无主题)";
    let badge = "";
    if (m.spam) badge = ` <span class="badge spam">垃圾 ${m.score}</span>`;
    else if (m.score > 0) badge = ` <span class="badge">分 ${m.score}</span>`;
    return `<tr class="row" data-id="${esc(m.id)}"><td>${esc(m.date)}</td><td>${esc(m.from)}${badge}</td><td>${esc(sub)}</td></tr>`;
  }).join("");
  $("view").innerHTML = `<div class="card"><table><thead><tr><th>时间</th><th>发件人</th><th>主题</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  $("view").querySelectorAll("tr.row").forEach((tr) => {
    tr.addEventListener("click", () => go("/mail/" + tr.dataset.id));
  });
}

async function viewInbox(group) {
  const folder = "inbox";
  const data = await api("/api/mails?" + new URLSearchParams({ folder, group: group || "" }));
  await refreshNav("inbox", group || "");
  renderList(group ? "收件箱 · " + group : "收件箱", data.mails || []);
}

async function viewFolder(folder, title) {
  const data = await api("/api/mails?" + new URLSearchParams({ folder }));
  await refreshNav(folder, "");
  renderList(title, data.mails || []);
}

async function viewMail(id) {
  const data = await api("/api/mail?" + new URLSearchParams({ id }));
  const m = data.mail;
  await refreshNav(m.folder, "");
  $("title").textContent = m.subject || "(无主题)";
  const btns = [`<button class="btn ghost" data-act="delete">删除</button>`];
  if (m.folder !== "spam") btns.push(`<button class="btn ghost" data-act="spam">标为垃圾</button>`);
  if (m.folder === "spam") btns.push(`<button class="btn ghost" data-act="ham">不是垃圾</button>`);
  $("actions").innerHTML = btns.join(" ");
  $("view").innerHTML = `<div class="card">
    <p><span class="muted">发件人</span> ${esc(m.from)}<br>
    <span class="muted">收件人</span> ${esc(m.to)}<br>
    <span class="muted">时间</span> ${esc(m.date)}<br>
    <span class="muted">文件夹</span> ${esc(m.folder)} · 垃圾分 ${m.score}</p>
    <pre class="body">${esc(m.body)}</pre>
  </div>`;
  $("actions").onclick = async (ev) => {
    const act = ev.target.dataset.act;
    if (!act) return;
    const path = act === "delete" ? "/api/mail/delete" : act === "spam" ? "/api/mail/spam" : "/api/mail/ham";
    await post(path, { id: m.id });
    go(act === "spam" ? "/spam" : "/inbox");
  };
}

async function viewCompose() {
  const [meta, contacts] = await Promise.all([api("/api/meta"), api("/api/contacts")]);
  await refreshNav("compose", "");
  $("title").textContent = "写邮件";
  $("actions").innerHTML = "";
  const opts = [`<option value="">从联系人填入…</option>`]
    .concat((contacts.contacts || []).map((c) => `<option value="${esc(c.email)}">${esc(c.name)} &lt;${esc(c.email)}&gt;</option>`))
    .join("");
  $("view").innerHTML = `<div class="card">
    <form id="compose-form">
      <label>发件人</label><input name="from" value="${esc(meta.user)}@${esc(meta.domain)}">
      <label>收件人（本地 @xu.local，逗号分隔）</label>
      <input id="to" name="to" placeholder="bob@xu.local">
      <label>联系人</label><select id="pick">${opts}</select>
      <label>主题</label><input name="subject">
      <label>正文</label><textarea name="body"></textarea>
      <p><button class="btn" type="submit">发送</button></p>
    </form>
  </div>`;
  $("pick").onchange = () => { if ($("pick").value) $("to").value = $("pick").value; };
  $("compose-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    await post("/api/compose", Object.fromEntries(fd.entries()));
    go("/sent");
  };
}

async function viewContacts() {
  const [contacts, groups] = await Promise.all([api("/api/contacts"), api("/api/groups")]);
  await refreshNav("contacts", "");
  $("title").textContent = "联系人";
  $("actions").innerHTML = "";
  const gopts = (groups.groups || []).map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
  const rows = (contacts.contacts || []).map((c) => `<tr>
    <td>${esc(c.name)}</td><td>${esc(c.email)}</td>
    <td><span class="badge">${esc(c.group)}</span></td>
    <td><button class="btn ghost" data-email="${esc(c.email)}">删除</button></td>
  </tr>`).join("") || `<tr><td colspan="4" class="muted">还没有联系人</td></tr>`;
  $("view").innerHTML = `<div class="grid2">
    <div class="card"><table><thead><tr><th>姓名</th><th>邮箱</th><th>分组</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="card"><h2>添加 / 更新</h2>
      <form id="contact-form">
        <label>姓名</label><input name="name">
        <label>邮箱</label><input name="email" placeholder="bob@xu.local">
        <label>分组</label><select name="group">${gopts}</select>
        <p><button class="btn" type="submit">保存</button></p>
      </form>
    </div>
  </div>`;
  $("view").querySelectorAll("button[data-email]").forEach((btn) => {
    btn.onclick = async () => {
      await post("/api/contacts/delete", { email: btn.dataset.email });
      route();
    };
  });
  $("contact-form").onsubmit = async (ev) => {
    ev.preventDefault();
    await post("/api/contacts", Object.fromEntries(new FormData(ev.target).entries()));
    route();
  };
}

async function viewGroups() {
  const groups = await api("/api/groups");
  await refreshNav("groups", "");
  $("title").textContent = "联系人分组";
  $("actions").innerHTML = "";
  const rows = (groups.groups || []).map((g) => `<tr>
    <td>${esc(g)}</td>
    <td><a href="#/inbox?group=${encodeURIComponent(g)}">查看该组来信</a></td>
    <td><button class="btn ghost" data-name="${esc(g)}">删除</button></td>
  </tr>`).join("");
  $("view").innerHTML = `<div class="grid2">
    <div class="card"><table><thead><tr><th>分组</th><th></th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="card"><h2>新建分组</h2>
      <form id="group-form">
        <label>名称</label><input name="name" placeholder="家人">
        <p><button class="btn" type="submit">添加</button></p>
      </form>
    </div>
  </div>`;
  $("view").querySelectorAll("button[data-name]").forEach((btn) => {
    btn.onclick = async () => {
      await post("/api/groups/delete", { name: btn.dataset.name });
      route();
    };
  });
  $("group-form").onsubmit = async (ev) => {
    ev.preventDefault();
    await post("/api/groups", Object.fromEntries(new FormData(ev.target).entries()));
    route();
  };
}

async function viewRules() {
  const rules = await api("/api/rules");
  await refreshNav("rules", "");
  $("title").textContent = "垃圾邮件规则";
  $("actions").innerHTML = "";
  const rows = (rules.rules || []).map((w) => `<tr>
    <td>${esc(w)}</td>
    <td><button class="btn ghost" data-word="${esc(w)}">删除</button></td>
  </tr>`).join("");
  $("view").innerHTML = `<p class="muted">命中关键词加分；全大写主题、过多链接也会加分。通讯录里非「其它」分组的发件人减分。超过 ${rules.threshold} 分进垃圾箱。</p>
    <div class="grid2">
      <div class="card"><table><thead><tr><th>关键词</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="card"><h2>添加关键词</h2>
        <form id="rule-form">
          <label>词或短语</label><input name="word">
          <p><button class="btn" type="submit">添加</button></p>
        </form>
      </div>
    </div>`;
  $("view").querySelectorAll("button[data-word]").forEach((btn) => {
    btn.onclick = async () => {
      await post("/api/rules/delete", { word: btn.dataset.word });
      route();
    };
  });
  $("rule-form").onsubmit = async (ev) => {
    ev.preventDefault();
    await post("/api/rules", Object.fromEntries(new FormData(ev.target).entries()));
    route();
  };
}

async function route() {
  flash("");
  const { segs, q } = hashParts();
  const page = segs[0] || "inbox";
  try {
    if (page === "inbox") await viewInbox(q.get("group") || "");
    else if (page === "sent") await viewFolder("sent", "已发送");
    else if (page === "spam") await viewFolder("spam", "垃圾箱");
    else if (page === "compose") await viewCompose();
    else if (page === "mail") await viewMail(segs[1] || "");
    else if (page === "contacts") await viewContacts();
    else if (page === "groups") await viewGroups();
    else if (page === "rules") await viewRules();
    else await viewInbox("");
  } catch (err) {
    flash(err.message || String(err), false);
  }
}

$("user").addEventListener("change", route);
window.addEventListener("hashchange", route);
if (!location.hash) location.hash = "#/inbox";
else route();
