"use strict";
(() => {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const S = { view: null, busy: false, llm: false, knownJournal: new Set(), firstRender: true, tab: "here" };

  async function api(path, body) {
    const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 2600);
  }

  // ---------------- start screen ----------------
  async function boot() {
    try {
      const st = await api("/api/status");
      S.llm = st.llm;
      $("#btn-continue").hidden = !st.has_save;
      $("#start-note").textContent = st.llm ? "說書人已就座。" : "說書人今天沒來，故事由鎮上的老規矩來講。";
    } catch (e) {
      $("#start-note").textContent = "連不上遊戲伺服器。";
    }
  }
  $("#btn-new").onclick = async () => {
    const d = await api("/api/backgrounds");
    const box = $("#bg-cards");
    box.replaceChildren();
    for (const c of d.choices) {
      const card = el("button", "bg-card");
      card.append(el("h3", null, c.name), el("p", null, c.desc));
      card.onclick = async () => {
        card.disabled = true;
        try { enter(await api("/api/new", { background: c.key })); } catch (e) { toast(e.message); card.disabled = false; }
      };
      box.append(card);
    }
    $("#start-buttons").hidden = true;
    $("#bg-pick").hidden = false;
  };
  $("#bg-back").onclick = () => { $("#start-buttons").hidden = false; $("#bg-pick").hidden = true; };
  $("#btn-continue").onclick = async () => {
    try { enter(await api("/api/continue", {})); } catch (e) { toast(e.message); }
  };

  function enter(resp) {
    $("#start").hidden = true;
    $("#game").hidden = false;
    render(resp);
  }

  // ---------------- turn rendering ----------------
  const TAGS = { witness: "眼前", overheard: "耳聞", news: "傳聞", approach: "" };

  function beatEl(b) {
    const p = el("p", `beat k-${b.kind}`);
    if (b.kind === "arrive" && b.text.startsWith("你來到")) {
      const i = b.text.indexOf("。");
      const place = el("span", "place", b.text.slice(0, i + 1));
      p.append(place, document.createTextNode(b.text.slice(i + 1)));
      return p;
    }
    if (TAGS[b.kind]) p.append(el("span", "tag", TAGS[b.kind]));
    p.append(document.createTextNode(b.text));
    return p;
  }

  function reveal(nodes) {
    nodes.forEach((n, i) => setTimeout(() => { n.classList.add("in"); scrollStory(); }, 90 * i + 20));
  }
  function scrollStory() {
    const s = $("#story");
    s.scrollTop = s.scrollHeight;
  }

  function renderTurn(beats, job, rewriteKinds) {
    if (!beats || !beats.length) return;
    const story = $("#story");
    const turn = el("div", "turn");
    story.append(turn);
    const rewrite = new Set(rewriteKinds || []);
    const nodes = [];
    let holder = null;
    const originals = [];
    for (const b of beats) {
      if (job && rewrite.has(b.kind)) {
        originals.push(b);
        if (!holder) {
          holder = el("div", "holder");
          const t = el("p", "beat thinking");
          t.append(document.createTextNode("說書人清了清嗓子"), el("span", "dots"));
          holder.append(t);
          turn.append(holder);
          nodes.push(t);
        }
        continue;
      }
      const n = beatEl(b);
      turn.append(n);
      nodes.push(n);
    }
    reveal(nodes);
    if (holder) pollNarration(job, holder, originals);
    // keep the log from growing forever
    while (story.children.length > 60) story.firstChild.remove();
  }

  async function pollNarration(job, holder, originals) {
    const started = Date.now();
    const fill = (items) => {
      holder.replaceChildren(...items);
      reveal(items);
    };
    const fallback = () => fill(originals.map(beatEl));
    while (Date.now() - started < 75000) {
      await new Promise((r) => setTimeout(r, 600));
      let d;
      try { d = await api(`/api/narration?id=${encodeURIComponent(job)}`); } catch (e) { break; }
      if (d.status === "done") {
        if (d.source === "llm") {
          fill(d.text.split(/\n+/).filter(Boolean).map((t) => el("p", "beat k-narration", t)));
        } else fallback();
        return;
      }
      if (d.status === "unknown") break;
    }
    fallback();
  }

  // ---------------- actions ----------------
  const ORDER = ["pending", "talk", "role", "ask", "tell", "money", "accuse", "people", "here", "move", "self"];
  const TITLES = { pending: "此刻，你要怎麼做？", talk: "交談", ask: "打聽某人", tell: "說出你知道的事", money: "錢與東西",
    role: "其他", accuse: "向捕頭指認", people: "這裡的人", here: "此地", move: "前往", self: "自己" };
  const COLLAPSED = new Set(["ask", "tell", "accuse", "money"]);

  function renderActions(v) {
    const box = $("#actions");
    box.replaceChildren();
    if (v.conversation) {
      const c = el("div", "convo");
      c.append(el("span", "who", `與${v.conversation.name}交談`), el("span", "att", `${v.conversation.look}；${v.conversation.attitude}`));
      box.append(c);
    }
    const groups = {};
    for (const a of v.actions) (groups[a.group] = groups[a.group] || []).push(a);
    const present = Object.fromEntries((v.present || []).map((p) => [p.key, p]));
    let k = 0;
    const numbered = [];
    for (const g of ORDER) {
      const list = groups[g];
      if (!list) continue;
      let wrap, btns = el("div", "btns");
      if (COLLAPSED.has(g)) {
        wrap = el("details", "group");
        wrap.append(el("summary", null, `${TITLES[g]}（${list.length}）`));
      } else {
        wrap = el("div", "group");
        wrap.append(el("div", "group-title", TITLES[g] || g));
      }
      for (const a of list) {
        const b = el("button", "act");
        if (a.hint === "risky") b.classList.add("risky");
        if (a.hint === "closed") b.classList.add("closed");
        if (g === "pending") b.classList.add("pend");
        if (a.hint === "info") b.disabled = true;
        if (g === "people") {
          const key = a.id.split(":")[1];
          const p = present[key];
          b.classList.add("person-btn");
          b.append(el("span", null, a.label));
          if (p) { b.append(el("small", null, p.look)); b.title = p.appearance || ""; }
        } else {
          b.append(document.createTextNode(a.label));
        }
        if (!COLLAPSED.has(g) && k < 9 && !b.disabled) {
          k += 1;
          b.prepend(el("span", "k", String(k)));
          numbered.push(a.id);
        }
        b.onclick = () => act(a.id);
        btns.append(b);
      }
      wrap.append(btns);
      box.append(wrap);
      if (g === "talk" && v.conversation) {
        const row = el("form", "say-row");
        const inp = el("input");
        inp.placeholder = `對${v.conversation.name}說……`;
        inp.maxLength = 80;
        const send = el("button", null, "說");
        send.type = "submit";
        row.append(inp, send);
        row.onsubmit = (e) => { e.preventDefault(); const t = inp.value.trim(); if (t) act("say", t); };
        box.insertBefore(row, wrap.nextSibling);
      }
    }
    S.numbered = numbered;
  }

  async function act(id, text) {
    if (S.busy) return;
    S.busy = true;
    document.querySelectorAll("#actions button").forEach((b) => (b.disabled = true));
    try {
      const resp = await api("/api/act", text ? { id, text } : { id });
      render(resp);
    } catch (e) {
      toast(e.message);
      document.querySelectorAll("#actions button").forEach((b) => (b.disabled = false));
    } finally {
      S.busy = false;
    }
  }

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^[1-9]$/.test(e.key) && S.numbered && S.numbered[+e.key - 1]) {
      e.preventDefault();
      act(S.numbered[+e.key - 1]);
    }
  });

  // ---------------- side panel ----------------
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.onclick = () => {
      S.tab = b.dataset.tab;
      document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
      document.querySelectorAll(".tab-body").forEach((x) => (x.hidden = x.id !== `tab-${S.tab}`));
    };
  });
  $("#drawer-btn").onclick = () => $("#side").classList.toggle("open");
  $("#story").addEventListener("click", () => $("#side").classList.remove("open"));

  function renderSide(v) {
    // 此地
    const here = $("#tab-here");
    here.replaceChildren(el("h2", null, v.location.name), el("p", "desc", v.location.desc));
    here.append(el("h3", null, "這裡的人"));
    if (v.present.length) {
      const ul = el("ul", "plist");
      for (const p of v.present) {
        const li = el("li");
        li.append(el("div", "nm", p.label), el("div", "sub", p.look));
        li.title = p.appearance || "";
        ul.append(li);
      }
      here.append(ul);
    } else here.append(el("p", "empty", "四下無人。"));
    here.append(el("h3", null, "從這裡可以去"), el("p", "desc", v.location.exits.join("、")));

    // 見聞錄
    const jb = $("#tab-journal");
    const prevFilter = jb.querySelector("input") ? jb.querySelector("input").value : "";
    jb.replaceChildren();
    const f = el("input", "jfilter");
    f.placeholder = "找人名或關鍵字……";
    f.value = prevFilter;
    jb.append(f);
    const list = el("div");
    jb.append(list);
    const draw = () => {
      list.replaceChildren();
      const q = f.value.trim();
      const items = v.journal.filter((j) => !q || j.text.includes(q) || j.people.some((p) => p.includes(q)));
      if (!items.length) list.append(el("p", "empty", v.journal.length ? "沒有符合的見聞。" : "你剛到鎮上，還什麼都不知道。"));
      for (const j of items) {
        const d = el("div", "jentry" + (!S.firstRender && !S.knownJournal.has(j.key) ? " new" : ""));
        d.append(el("div", "meta", `${j.day >= 1 ? `第${j.day}日` : "你來之前"} · ${j.source}`), el("div", null, j.text));
        list.append(d);
      }
    };
    f.oninput = draw;
    draw();
    v.journal.forEach((j) => S.knownJournal.add(j.key));

    // 人物
    const pb = $("#tab-people");
    pb.replaceChildren();
    if (!v.people.length) pb.append(el("p", "empty", "你還沒跟誰說過話。"));
    const ul = el("ul", "plist");
    for (const p of v.people) {
      const li = el("li");
      const nm = el("div", "nm", `${p.name}　`);
      nm.append(el("span", "sub", p.role));
      if (p.status) nm.append(el("span", "st", p.status));
      li.append(nm, el("div", "sub", p.attitude + (p.last_seen ? `；上次見到是第${p.last_seen.day}日，在${p.last_seen.place}` : "")));
      ul.append(li);
    }
    pb.append(ul);

    // 足跡
    const db = $("#tab-deeds");
    db.replaceChildren();
    if (!v.deeds.length) db.append(el("p", "empty", "你在這個鎮上還沒留下什麼痕跡。"));
    for (const d of v.deeds) db.append(el("div", "jentry", d));

    // 行囊
    const kb = $("#tab-pack");
    const pl = v.player;
    kb.replaceChildren(el("h2", null, pl.background));
    const stat = (a, b) => { const r = el("div", "stat"); r.append(el("span", null, a), el("span", null, b)); kb.append(r); };
    stat("銀錢", `${pl.money} 文`);
    stat("身子", pl.health_word);
    stat("身手", pl.prowess_word);
    stat("藥", pl.medicine ? `${pl.medicine} 帖` : "沒有");
    kb.append(el("h3", null, "你欠的"));
    if (!pl.debts.length) kb.append(el("p", "empty", "一身輕。"));
    for (const d of pl.debts) stat(d.to, `${d.amount} 文，第${d.due_day}日前`);
    kb.append(el("h3", null, "欠你的"));
    if (!pl.owed.length) kb.append(el("p", "empty", "沒有。"));
    for (const d of pl.owed) stat(d.by, `${d.amount} 文，第${d.due_day}日前`);
  }

  function renderTop(v) {
    $("#clock").textContent = `第${v.day}日 · ${v.period} · ${v.weather}`;
    $("#where").textContent = v.location.name + (v.player.jailed ? "（拘房）" : "");
    const me = $("#me");
    me.replaceChildren();
    const b = (t) => el("b", null, t);
    me.append(b(`${v.player.money}`), document.createTextNode(" 文　"), b(v.player.health_word));
  }

  function render(resp) {
    const v = resp.view;
    S.view = v;
    renderTop(v);
    renderTurn(v.beats, resp.narration, resp.rewrite_kinds);
    renderActions(v);
    renderSide(v);
    S.firstRender = false;
  }

  boot();
})();
