"use strict";
const $ = (s, el = document) => el.querySelector(s);
const view = () => $("#view");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let timer = null, seq = 0;
const live = id => id === seq;  // a page that finished loading after the user moved on must not draw

async function api(path, opt = {}) {
  const r = await fetch("/api/" + path, {
    method: opt.method || "GET", credentials: "same-origin",
    headers: { "X-CBS": "1", "Content-Type": "application/json" },
    body: opt.body === undefined ? undefined : JSON.stringify(opt.body),
  });
  if (r.status === 401) { showLogin(); throw new Error("login"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function toast(text) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = text;
  document.body.append(t); setTimeout(() => t.remove(), 2600);
}

const pad = n => String(n).padStart(2, "0");
const hm = t => { const d = new Date(t * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const md_ = t => { const d = new Date(t * 1000); return `${d.getMonth() + 1} 月 ${d.getDate()} 日`; };
function later(t, now) {
  if (!t) return "随时";
  const m = Math.round((t - now) / 60);
  if (m <= 0) return "马上";
  if (m < 60) return `${m} 分钟后`;
  return `${Math.floor(m / 60)} 小时 ${m % 60 ? (m % 60) + " 分" : ""}后`;
}

function inline(s) {
  const keep = [];
  const put = html => `\u0000${keep.push(html) - 1}\u0000`;
  s = s.replace(/`([^`]+)`/g, (_, c) => put(`<code>${c}</code>`));
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, t, u) => put(`<a href="${u}" target="_blank" rel="noopener">${t}</a>`));
  s = s.replace(/https?:\/\/[^\s<]+/g, u => put(`<a href="${u}" target="_blank" rel="noopener">${u}</a>`));
  s = s.replace(/(^|[^\/\w])(BV[0-9A-Za-z]{10})/g, (_, p, bv) => p + put(`<a href="https://www.bilibili.com/video/${bv}" target="_blank" rel="noopener">${bv}</a>`));
  s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[i]);
}

function md(text) {
  const out = [], lines = esc(text).split(/\r?\n/);
  let list = null, para = [], code = null;
  const flushPara = () => { if (para.length) out.push(`<p>${inline(para.join("<br>"))}</p>`); para = []; };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (const line of lines) {
    if (code !== null) {
      if (line.startsWith("```")) { out.push(`<pre><code>${code.join("\n")}</code></pre>`); code = null; } else code.push(line);
      continue;
    }
    if (line.startsWith("```")) { flushPara(); flushList(); code = []; continue; }
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { flushPara(); flushList(); const n = Math.min(m[1].length + 1, 4); out.push(`<h${n}>${inline(m[2])}</h${n}>`); continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
      flushPara();
      const tag = /^\s*\d/.test(line) ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
      list.items.push(m[1]); continue;
    }
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = line.match(/^&gt;\s?(.*)/))) { flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (!line.trim()) { flushPara(); flushList(); continue; }
    flushList(); para.push(line);
  }
  if (code !== null) out.push(`<pre><code>${code.join("\n")}</code></pre>`);
  flushPara(); flushList();
  return `<div class="md">${out.join("")}</div>`;
}

const moodWord = s => (s.mood || "").trim().split(/\s+/)[0] || "";
const moodWhy = s => (s.mood || "").trim().split(/\s+/).slice(1).join(" ");
function face(s) {
  if (s.state === "asleep" || s.state === "paused") return "sleepy";
  if (s.state === "browsing") return "browsing";
  const w = moodWord(s);
  if (["开心", "兴奋"].includes(w)) return "happy";
  if (["吃醋", "想你"].includes(w)) return "jealous";
  if (w === "犯困") return "sleepy";
  return "normal";
}
const STATE = { awake: "醒着", busy: "在忙", browsing: "在刷站", asleep: "睡着了", paused: "暂停中" };
function voice(s) {
  if (s.state === "paused") return "被你按了暂停。本小姐歇一会儿，想我了再点继续。";
  if (s.state === "asleep") return `睡了。${s.plan ? hm(s.plan.wake) : "明早"}左右醒，有事先留言。`;
  if (s.state === "busy") return `${s.why || "在忙"}，晚点再回你。`;
  if (s.state === "browsing") return "在刷站呢。刷到好东西会告诉你的，别催。";
  return moodWhy(s) || "醒着，闲着。你要是有空，可以来找本小姐聊聊。";
}
const ava = (img = "normal", size = 32) => `<div class="ava" style="width:${size}px;height:${size}px;background-image:url(img/${img}.webp)"></div>`;
const empty = (text, img = "normal") => `<div class="empty">${ava(img, 76)}${esc(text)}</div>`;
const ICON = {
  heart: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  play: '<rect x="3" y="5" width="18" height="13" rx="2"/><path d="m10 9 5 2.5-5 2.5z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m4 7 8 6 8-6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
};
const icon = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICON[n]}</svg>`;
function setMini(s) {
  const m = $("#mini");
  if (m) m.innerHTML = `${ava(face(s), 38)}<div class="who"><b>Claude 大小姐</b><span>${STATE[s.state] || s.state}${moodWord(s) ? " · " + esc(moodWord(s)) : ""}</span></div>`;
}

function dayBar(s) {
  const p = s.plan;
  if (!p) return "";
  const d = new Date(p.wake * 1000);
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 6).getTime() / 1000, span = 22 * 3600;
  const x = t => Math.max(0, Math.min(100, (t - start) / span * 100));
  const busy = p.busy.map(([a, b, why]) => `<div class="busy" title="${esc(why)} ${hm(a)} 到 ${hm(b)}" style="left:${x(a)}%;width:${x(b) - x(a)}%"></div>`).join("");
  const now = s.now >= start && s.now <= start + span ? `<div class="now" style="left:${x(s.now)}%"></div>` : "";
  const marks = [6, 10, 14, 18, 22, 2].map(h => `<span>${pad(h)}:00</span>`).join("");
  return `<div class="card"><div class="card-head"><h3>今天的作息</h3>
    <span class="muted small">${md_(p.wake)}，${hm(p.wake)} 起床，${hm(p.sleep)} 睡觉</span></div>
    <div class="day"><div class="awake" style="left:${x(p.wake)}%;width:${x(p.sleep) - x(p.wake)}%"></div>${busy}${now}</div>
    <div class="day-scale">${marks}</div>
    <div class="legend"><span><i style="background:color-mix(in srgb,var(--accent) 28%,transparent)"></i>醒着</span>
    <span><i style="background:repeating-linear-gradient(135deg,var(--busy) 0 3px,transparent 3px 5px)"></i>在忙（${p.busy.map(b => esc(b[2])).join("、") || "今天没安排"}）</span></div></div>`;
}

function bubbles(chat, owner) {
  let lastDay = "";
  return chat.map(e => {
    const day = md_(e.t), sep = day !== lastDay ? `<div class="daysep">${day}</div>` : "";
    lastDay = day;
    const me = e.who === "owner", bot = e.who === "bot";
    const who = me ? owner : bot ? "她" : (e.from || "陌生人");
    const where = e.channel === "dm" ? "私信" : `评论${e.title ? " · " + (e.title.length > 14 ? e.title.slice(0, 14) + "…" : e.title) : ""}`;
    const kind = bot && e.kind === "proactive" ? `<span class="pill accent tag">主动找你</span>` : bot && e.kind === "nudge" ? `<span class="pill accent tag">轻轻问候</span>` : "";
    const link = e.bvid ? ` · <a href="https://www.bilibili.com/video/${esc(e.bvid)}" target="_blank" rel="noopener">${esc(e.bvid)}</a>` : "";
    const av = bot ? ava("normal", 32) : `<div class="letter">${esc(who.slice(0, 1))}</div>`;
    return `${sep}<div class="msg ${me ? "me" : bot ? "" : "stranger"}">${av}<div><div class="t">${esc(who)} · ${hm(e.t)} · ${esc(where)}${link}${kind}</div>
      <div class="b">${inline(esc(e.text))}</div></div></div>`;
  }).join("");
}

const pages = {};

pages[""] = async () => {
  const id = seq;
  const [s, chat, journals] = await Promise.all([api("status"), api("chat?days=3"), api("files/journal")]);
  const recent = chat.filter(e => e.who !== "stranger").slice(-6);
  const daily = journals.find(n => !n.startsWith("week-"));
  const journal = daily ? (await api("files/journal/" + daily)).text : "";
  if (!live(id)) return;
  const last = journal.split(/\n(?=## )/).filter(x => x.startsWith("## ")).pop() || "";
  const running = s.jobs.length ? s.jobs.map(j => `<span class="pill accent"><span class="dot live"></span>${esc({ browse: "刷站", inbox: "看消息", daily: "写日报", dryrun: "试运行" }[j] || j)}</span>`).join("") : "";
  const h = new Date().getHours(), d = new Date();
  const notes = [s.logged_in ? "" : "小号还没登录，去运行页扫码。", s.life_on ? "" : "作息模式没开，在设置里把 [life] 的 enabled 改成 true。"].filter(Boolean);
  const nextBrowse = s.jobs.includes("browse") ? "刷着呢" : !s.life_on ? "按日报时间"
    : s.next_session > s.now ? later(s.next_session, s.now) : { busy: "忙完就刷", asleep: "睡醒再说", paused: "暂停中" }[s.state] || "马上";
  const stat = (ic, label, value, sub, extra = "", lead = false) => `<div class="card stat${lead ? " lead" : ""}">
    <div class="top"><span class="ico">${icon(ic)}</span>${label}</div><div class="value">${value}</div>${extra}<div class="sub">${sub || "&nbsp;"}</div></div>`;
  setMini(s);
  view().innerHTML = `
    <div class="grid">
      <div class="card hero">
        <div class="figure"><img src="img/${face(s)}.webp" alt="Claude 大小姐"></div>
        <div class="talk">
          <p class="hello">${h < 5 ? "还没睡呀" : h < 11 ? "早" : h < 18 ? "下午好" : "晚上好"}，${esc(s.owner)}</p>
          <p class="date">${d.getMonth() + 1} 月 ${d.getDate()} 日，星期${"日一二三四五六"[d.getDay()]}</p>
          <div class="bubble">${esc(voice(s))}</div>
          <div class="meta"><span class="pill ${s.state === "browsing" ? "accent" : ""}"><span class="dot ${s.state === "browsing" ? "live" : s.state === "awake" ? "ok" : ""}"></span>${STATE[s.state] || s.state}</span>
          ${moodWord(s) ? `<span class="pill">心情 ${esc(moodWord(s))}</span>` : ""}${running}</div></div>
      </div>
      ${notes.length ? `<div class="card small" style="background:var(--accent-50);box-shadow:none;color:var(--accent-700)">${notes.join(" ")}</div>` : ""}
      <div class="grid g4">
        ${stat("heart", "今天主动找你", `${s.contacts_today}<small>/ ${s.max_contacts}</small>`,
          s.can_contact ? (s.can_contact === "nudge" ? "你两次没回，她可能会轻轻问一句" : "想找你的时候会找") : esc(s.contact_note),
          `<div class="meter"><i style="width:${Math.min(100, s.contacts_today / Math.max(1, s.max_contacts) * 100)}%"></i></div>`, true)}
        ${stat("play", "下次刷站", nextBrowse, s.life_on && s.next_session > s.now && !s.jobs.includes("browse") ? hm(s.next_session) + " 前后" : "")}
        ${stat("mail", "下次看消息", s.jobs.includes("inbox") ? "看着呢" : later(s.next_inbox, s.now), s.state === "asleep" ? "睡醒再看" : s.state === "busy" ? "在忙，回得慢" : "")}
        ${stat("sun", "作息", s.plan ? hm(s.plan.wake) + " 到 " + hm(s.plan.sleep) : "未开", "每天随机浮动一点")}
      </div>
      ${dayBar(s)}
      <div class="grid g2 top">
        <div class="card"><div class="card-head"><h3>最近的聊天</h3><a href="#/chat" class="small">全部</a></div>
          <div class="chat">${recent.length ? bubbles(recent, s.owner) : empty("这几天还没聊过。去 B 站私信本小姐试试？")}</div></div>
        <div class="card"><div class="card-head"><h3>最近一次刷站</h3><a href="#/journal" class="small">日记</a></div>
          <div>${last ? md(last) : empty("今天还没刷。醒着有空就会去的。", "browsing")}</div></div>
      </div>
    </div>`;
  timer = setTimeout(route, 20000);
};

pages.chat = async () => {
  const id = seq;
  const [s, chat] = await Promise.all([api("status"), api("chat?days=30")]);
  if (!live(id)) return;
  setMini(s);
  const draw = () => {
    const all = $("#strangers").checked;
    const rows = chat.filter(e => all || e.who !== "stranger");
    $("#chat").innerHTML = rows.length ? bubbles(rows, s.owner) : empty("还没有聊天记录。私信小号说句话，这里就有了。");
    window.scrollTo(0, document.body.scrollHeight);
  };
  view().innerHTML = `<div class="page-head"><div><h1>对话</h1><p>最近 30 天的私信和评论。</p></div><label class="row small muted"><input type="checkbox" id="strangers"> 显示陌生人</label></div>
    <div class="card"><div class="chat" id="chat"></div></div>`;
  $("#strangers").onchange = draw;
  draw();
};

async function docView(folders, title, hint, img) {
  let folder = folders[0][0], names = [];
  const id = seq;
  view().innerHTML = `<div class="page-head"><div><h1>${title}</h1><p>${hint}</p></div></div>
    ${folders.length > 1 ? `<div class="tabs" id="tabs" style="margin-bottom:14px">${folders.map(([f, n]) => `<button data-f="${f}">${n}</button>`).join("")}</div>` : ""}
    <div class="split"><div class="card list" id="names"></div><div class="card doc" id="doc"></div></div>`;
  const open = async name => {
    $("#names").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.n === name));
    const { text } = await api(`files/${folder}/${encodeURIComponent(name)}`);
    if (live(id)) $("#doc").innerHTML = md(text);
  };
  const load = async f => {
    folder = f;
    $("#tabs")?.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.f === f));
    names = await api("files/" + f);
    if (!live(id)) return;
    $("#names").innerHTML = names.map(n => `<button data-n="${esc(n)}">${esc(n.replace(/\.md$/, ""))}</button>`).join("") || `<span class="muted small" style="padding:8px">空的</span>`;
    $("#names").querySelectorAll("button").forEach(b => b.onclick = () => open(b.dataset.n));
    if (names.length) await open(names[0]); else $("#doc").innerHTML = empty("这里还什么都没有。", img);
  };
  $("#tabs")?.querySelectorAll("button").forEach(b => b.onclick = () => load(b.dataset.f));
  await load(folder);
}

pages.journal = () => docView([["journal", "日记"]], "刷站日记", "她每次刷完随手记的，周日晚上还有一篇周回顾。", "browsing");
pages.files = () => docView([["out", "日报"], ["inbox", "回复记录"], ["digest", "月度归档"]], "档案", "以前的日报、每条回复的记录和按月的归档。", "normal");

const MEMORY = [
  ["owner.md", "关于你", "她记下的你的事，喜欢什么、重要的日子、说过要回头看的东西。"],
  ["topics.md", "在聊的话题", "你们最近聊着的事，她会接着往下说。"],
  ["interests.md", "她的兴趣", "她自己的兴趣，会慢慢变。刷站时会照着它找视频。"],
  ["mood.txt", "心情", "一行字，开头一个词决定概览页的表情。"],
];
pages.memory = async () => {
  const id = seq, mem = await api("memory");
  if (!live(id)) return;
  view().innerHTML = `<div class="page-head"><div><h1>记忆</h1><p>她自己维护这些文件。你也可以直接改，下一轮她就会读到。</p></div></div>
    <div class="grid g2">${MEMORY.map(([n, t, h]) => `<div class="card"><h3>${t}</h3><p class="muted small" style="margin-top:-4px">${h}</p>
      <textarea class="edit${n === "mood.txt" ? " short" : ""}" data-n="${n}" placeholder="还是空的">${esc(mem[n])}</textarea>
      <div class="row end" style="margin-top:8px"><button class="btn primary" data-save="${n}">保存</button></div></div>`).join("")}</div>`;
  view().querySelectorAll("[data-save]").forEach(b => b.onclick = async () => {
    const n = b.dataset.save;
    try { await api("memory/" + n, { method: "PUT", body: { text: view().querySelector(`textarea[data-n="${n}"]`).value } }); toast("存好了"); }
    catch (e) { toast(e.message); }
  });
};

pages.settings = async () => {
  const id = seq, { text } = await api("config");
  if (!live(id)) return;
  view().innerHTML = `<div class="page-head"><div><h1>设置</h1><p>就是 config.toml。保存前会检查格式，不对就不存。</p></div></div>
    <div class="grid"><div class="card"><textarea class="edit tall" id="cfg" spellcheck="false">${esc(text)}</textarea>
      <div class="row" style="justify-content:space-between;margin-top:10px"><span class="muted small">下一轮开始生效。[web] 的地址和端口要重新运行一次 schedule 才会换。</span>
      <button class="btn primary" id="save">保存</button></div></div>
    <div class="card small"><h3>常改的几项</h3><div class="md"><ul>
      <li><code>[life] enabled</code> 打开作息模式，她会自己安排什么时候刷、什么时候找你。</li>
      <li><code>[life] wake</code> 和 <code>sleep</code> 是大概几点起、几点睡，每天会随机浮动一点。<code>owner_quiet</code> 是你睡觉的时段，这段时间她不会主动找你。</li>
      <li><code>[life] max_contacts_per_day</code> 是一天最多主动找你几次，<code>min_gap_minutes</code> 是两次之间至少隔多久。</li>
      <li><code>[comment] enabled</code> 打开以后，她刷到最值得的视频会在评论区 @ 你，一天最多 <code>max_per_run</code> 条。</li>
      <li><code>[web] password</code> 是这个页面的密码，改了马上生效。</li></ul></div></div></div>`;
  $("#save").onclick = async () => {
    try { await api("config", { method: "PUT", body: { text: $("#cfg").value } }); toast("存好了，下一轮生效"); }
    catch (e) { toast(e.message); }
  };
};

const ACTIONS = [
  ["browse", "现在刷一会儿", "不等作息，马上随手刷几条"],
  ["inbox", "现在看消息", "马上查一次 @、回复和私信"],
  ["dryrun", "试运行", "刷一轮但什么都不发，看她会怎么做"],
  ["daily", "写一份日报", "按老办法刷一轮，写进日报"],
  ["doctor", "体检", "检查登录、依赖和 agent"],
];
pages.run = async () => {
  const id = seq, s = await api("status");
  if (!live(id)) return;
  setMini(s);
  const JOB = { browse: "刷站", inbox: "看消息", daily: "写日报", dryrun: "试运行" };
  view().innerHTML = `<div class="page-head"><div><h1>运行</h1><p>${s.jobs.length ? "正在" + s.jobs.map(j => JOB[j] || j).join("、") : "现在没有在跑的任务"}</p></div></div>
    <div class="grid">
      <div class="card"><h3>手动操作</h3><div class="actions">
        ${ACTIONS.map(([a, t, h], i) => `<button class="btn${i === 0 && !s.paused ? " primary" : ""}" data-a="${a}"><b>${t}</b><span>${h}</span></button>`).join("")}
        <button class="btn${s.paused ? " primary" : ""}" data-a="${s.paused ? "resume" : "pause"}"><b>${s.paused ? "继续" : "暂停"}</b><span>${s.paused ? "恢复作息和查消息" : "先别刷也别回消息"}</span></button>
      </div>${s.doctor ? `<div class="log" style="margin-top:12px">${esc(s.doctor)}</div>` : ""}</div>
      <div class="grid g2">
        <div class="card"><h3>小号登录</h3><p class="muted small">${s.logged_in ? "已经登录。凭证过期了就在这里重新扫码。" : "还没登录。"}用小号的 B 站 App 扫码，确认时选"长期"。</p>
          <div id="qr" class="row" style="gap:16px"></div><button class="btn" id="qr-start" style="margin-top:10px">${s.logged_in ? "重新扫码登录" : "扫码登录"}</button></div>
        <div class="card"><h3>今天的状态</h3><dl class="facts">
          <div><dt>现在</dt><dd>${STATE[s.state] || s.state}${s.why ? "，" + esc(s.why) : ""}</dd></div>
          <div><dt>主动找你</dt><dd>${s.contacts_today} 次，上限 ${s.max_contacts} 次${s.can_contact ? "" : '<br><span class="muted small">' + esc(s.contact_note) + "</span>"}</dd></div>
          <div><dt>下次看消息</dt><dd>${later(s.next_inbox, s.now)}</dd></div>
          ${s.life_on ? `<div><dt>下次刷站</dt><dd>${later(s.next_session, s.now)}</dd></div>` : ""}</dl></div>
      </div>
      <div class="card"><div class="card-head"><h3>日志</h3>
        <div class="row"><select id="day" class="btn"></select><label class="row small muted"><input type="checkbox" id="follow" checked> 自动刷新</label></div></div>
        <div class="log" id="log"></div></div>
    </div>`;
  view().querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { await api("action", { method: "POST", body: { action: b.dataset.a } }); toast("收到，马上去"); }
    catch (e) { toast(e.message); b.disabled = false; return; }
    if ($("#qr-state")) return;  // a redraw would stop the QR login in the middle of a scan
    clearTimeout(timer);
    timer = setTimeout(route, 1500);
  });
  $("#qr-start").onclick = qrLogin;
  const logs = async day => {
    const r = await api("logs" + (day ? "?day=" + day : ""));
    const sel = $("#day");
    if (!sel) return;
    if (!sel.options.length) sel.innerHTML = r.days.map(d => `<option>${d}</option>`).join("");
    const box = $("#log"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    box.textContent = r.lines.join("\n") || "这天没有日志。";
    if (atEnd) box.scrollTop = box.scrollHeight;
  };
  $("#day").onchange = () => logs($("#day").value);
  await logs();
  const tick = async () => {
    if (!live(id) || !$("#log")) return;
    if ($("#follow").checked) await logs($("#day").value).catch(() => {});
    timer = setTimeout(tick, 5000);
  };
  timer = setTimeout(tick, 5000);
};

async function qrLogin() {
  const box = $("#qr"), btn = $("#qr-start");
  btn.disabled = true;
  try {
    const { key, svg } = await api("qr/start", { method: "POST", body: {} });
    box.innerHTML = `<div class="qr">${svg}</div><span class="muted small" id="qr-state">等你扫码，三分钟内有效</span>`;
    const until = Date.now() + 180000;
    const poll = async () => {
      if (!$("#qr-state")) return;
      let result;
      try { ({ result } = await api("qr/poll", { method: "POST", body: { key } })); }
      catch (e) { box.innerHTML = `<span class="muted small">登录没成功：${esc(e.message)}，再点一次</span>`; btn.disabled = false; return; }
      if (result === "ok") { box.innerHTML = `<span class="pill accent">登录好了</span>`; btn.disabled = false; return; }
      if (result === "expired" || Date.now() > until) { box.innerHTML = `<span class="muted small">二维码过期了，再点一次</span>`; btn.disabled = false; return; }
      setTimeout(poll, 2000);
    };
    setTimeout(poll, 2000);
  } catch (e) { toast(e.message); btn.disabled = false; }
}

async function route() {
  clearTimeout(timer);
  seq++;
  const name = location.hash.replace(/^#\/?/, "");
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#/" + name));
  try { await (pages[name] || pages[""])(); }
  catch (e) { if (e.message !== "login") view().innerHTML = empty("出了点问题：" + e.message, "sleepy"); }
}

function showLogin() { $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); $("#pw").focus(); }
function showApp() { $("#login").classList.add("hidden"); $("#app").classList.remove("hidden"); route(); }

$("#login-form").onsubmit = async ev => {
  ev.preventDefault();
  try { await api("login", { method: "POST", body: { password: $("#pw").value } }); $("#pw").value = ""; showApp(); }
  catch (e) { $("#login-err").textContent = e.message === "login" ? "密码不对" : e.message; }
};
$("#logout").onclick = async () => { await api("logout", { method: "POST", body: {} }).catch(() => {}); showLogin(); };
$("#theme").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t; localStorage.theme = t;
};
addEventListener("hashchange", route);
api("status").then(showApp, e => { if (e.message !== "login") showApp(); });
