/* Immo Search — front-end.
   No framework, no build step: the whole UI is a few hundred lines against the
   same JSON API the CLI uses, so what you see is exactly what the engine
   returned. State lives in the URL, so any search is a shareable link. */

(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const state = {
    rooms: new Set(), modes: new Set(), zones: new Set(),
    depts: new Set(), fiscal: new Set(), features: new Set(),
    page: 1, sort: "eur_m2", order: "asc", view: "cards",
    meta: null, last: null, seq: 0,
  };

  const LABELS = {
    q: "Recherche", kind: "Type", rooms_min: "Pièces ≥", rooms_max: "Pièces ≤",
    surface_min: "Surface ≥", surface_max: "Surface ≤", price_min: "Prix ≥",
    price_max: "Prix ≤", eur_m2_min: "€/m² ≥", eur_m2_max: "€/m² ≤",
    walk_max_m: "À pied ≤", crow_max_m: "Vol d'oiseau ≤", mode: "Mode",
    line: "Ligne", zone: "Zone", dept: "Dépt", city: "Commune",
    delivery_from: "Livraison ≥", delivery_to: "Livraison ≤", fiscal: "Dispositif",
    feature: "Équipement", kitchen: "Cuisine", floor_min: "Étage ≥",
    floor_max: "Étage ≤", exposure: "Exposition",
    with_exact_address: "Adresse exacte", with_photos: "Photos",
    with_plan: "Plan", carrez_only: "Carrez", only_available: "Disponible",
    keep_unknown: "Inclut données manquantes",
    include_atypical: "Mutations atypiques incluses",
  };

  const nf = new Intl.NumberFormat("fr-FR");
  const money = (v) => (v || v === 0 ? nf.format(Math.round(v)) + " €" : "—");
  const area = (v) => (v ? nf.format(Math.round(v * 10) / 10) + " m²" : "—");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ------------------------------------------------------------- criteria */

  function collect() {
    const p = {};
    const form = $("#filters");
    for (const el of form.elements) {
      if (!el.name || el.type === "radio" || el.type === "checkbox") continue;
      const v = el.value.trim();
      if (v) p[el.name] = v;
    }
    const kind = $("input[name=kind]:checked");
    if (kind && kind.value) p.kind = kind.value;
    $$("#filters input[type=checkbox]").forEach((c) => { if (c.checked) p[c.name] = "1"; });

    if (state.rooms.size) {
      const r = [...state.rooms].map(Number);
      p.rooms_min = String(Math.min(...r));
      if (!state.rooms.has("5")) p.rooms_max = String(Math.max(...r));
    }
    if (state.modes.size) p.mode = [...state.modes].join(",");
    if (state.zones.size) p.zone = [...state.zones].join(",");
    if (state.depts.size) p.dept = [...state.depts].join(",");
    if (state.fiscal.size) p.fiscal = [...state.fiscal].join(",");
    if (state.features.size) p.feature = [...state.features].join(",");

    p.sort = state.sort; p.order = state.order;
    p.page = String(state.page); p.per_page = "24";
    return p;
  }

  function applyToUrl(p) {
    const url = new URL(location.href);
    url.search = new URLSearchParams({ ...p, view: state.view }).toString();
    history.replaceState(null, "", url);
  }

  function restoreFromUrl() {
    const p = new URLSearchParams(location.search);
    if (![...p.keys()].length) return;
    const form = $("#filters");
    for (const [k, v] of p) {
      if (k === "view") { state.view = v; const r = $(`input[name=view][value=${v}]`); if (r) r.checked = true; continue; }
      if (k === "sort") { state.sort = v; continue; }
      if (k === "order") { state.order = v; continue; }
      if (k === "page") { state.page = Number(v) || 1; continue; }
      if (k === "kind") { const r = $(`input[name=kind][value="${v}"]`); if (r) r.checked = true; continue; }
      if (k === "mode") { v.split(",").forEach((x) => state.modes.add(x)); continue; }
      if (k === "zone") { v.split(",").forEach((x) => state.zones.add(x)); continue; }
      if (k === "dept") { v.split(",").forEach((x) => state.depts.add(x)); continue; }
      if (k === "fiscal") { v.split(",").forEach((x) => state.fiscal.add(x)); continue; }
      if (k === "feature") { v.split(",").forEach((x) => state.features.add(x)); continue; }
      if (k === "rooms_min" || k === "rooms_max") { state.rooms.add(v); continue; }
      const el = form.elements[k];
      if (!el) continue;
      if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
    }
    const sortSel = $("#sort");
    const combo = `${state.sort}|${state.order}`;
    if ([...sortSel.options].some((o) => o.value === combo)) sortSel.value = combo;
    syncChips();
  }

  function syncChips() {
    const map = [
      ["#roomChips .chip", "rooms", "rooms"],
      ["#modeChips .chip", "mode", "modes"],
      ["#zoneChips .chip", "zone", "zones"],
      ["#deptChips .chip", "dept", "depts"],
      ["#fiscalChips .chip", "fiscal", "fiscal"],
      ["#featureChips .chip", "feature", "features"],
    ];
    for (const [sel, attr, key] of map) {
      $$(sel).forEach((c) => c.setAttribute("aria-pressed", state[key].has(c.dataset[attr]) ? "true" : "false"));
    }
  }

  /* --------------------------------------------------------------- render */

  function activeChips(p) {
    const box = $("#activeChips");
    const skip = new Set(["sort", "order", "page", "per_page"]);
    const items = Object.entries(p).filter(([k]) => !skip.has(k));
    box.innerHTML = items.map(([k, v]) =>
      `<span class="achip">${esc(LABELS[k] || k)}: ${esc(v)}<button data-clear="${esc(k)}" aria-label="Retirer">✕</button></span>`
    ).join("");
  }

  function statBadge(l) {
    const facts = [];
    const choices = l.rooms_choices || [];
    if (choices.length > 1) {
      facts.push(`<span class="fact">T${Math.min(...choices)}–T${Math.max(...choices)}</span>`);
    } else if (l.rooms) {
      facts.push(`<span class="fact">T${l.rooms}</span>`);
    }
    if (l.surface) facts.push(`<span class="fact${l.surface_is_carrez ? " good" : ""}">${area(l.surface)}${l.surface_is_carrez ? " Carrez" : ""}</span>`);
    else facts.push(`<span class="fact unknown">surface ?</span>`);
    if (l.zone_abc) facts.push(`<span class="fact">zone ${esc(l.zone_abc)}</span>`);
    if (l.delivery_label) facts.push(`<span class="fact">livr. ${esc(l.delivery_label)}</span>`);
    if (l.sale_date) facts.push(`<span class="fact">vendu ${esc(l.sale_date)}</span>`);
    const st = l.nearest_station;
    if (st) {
      const d = st.walk_m ? `${Math.round(st.walk_m)} m à pied` : (st.crow_m ? `~${Math.round(st.crow_m)} m` : "");
      facts.push(`<span class="fact${st.walk_m && st.walk_m <= 450 ? " good" : ""}">${esc(st.mode)} ${esc(st.line || "")} · ${esc(d)}</span>`);
    }
    (l.fiscal || []).slice(0, 3).forEach((f) => facts.push(`<span class="fact">${esc(f)}</span>`));
    if (l.has_plan) facts.push(`<span class="fact good">plan</span>`);
    if (l.available === false) facts.push(`<span class="fact warn">lot vendu</span>`);
    if (!l.has_exact_address) facts.push(`<span class="fact unknown">adresse approx.</span>`);
    if (l.price_flag) facts.push(`<span class="fact warn">${esc(l.price_flag)}</span>`);
    return facts.join("");
  }

  function cardHtml(l) {
    return `<article class="card" data-id="${esc(l.id)}" tabindex="0">
      <div class="card-top">
        <div>
          <h3>${esc(l.name || "Sans nom")}</h3>
          <div class="where">${esc([l.city, l.dept && `(${l.dept})`, l.developer].filter(Boolean).join(" "))}</div>
        </div>
        <span class="kind ${esc(l.kind)}">${l.kind === "neuf" ? "Neuf" : "Vendu"}</span>
      </div>
      <div class="metrics">
        <div class="metric${l.eur_m2 ? "" : " dim"}"><div class="v">${l.eur_m2 ? nf.format(l.eur_m2) + " €/m²" : "€/m² n. d."}</div><div class="k">prix au m²</div></div>
        <div class="metric${l.price ? "" : " dim"}"><div class="v">${money(l.price)}</div><div class="k">${l.kind === "neuf" ? "prix affiché" : "prix de vente"}</div></div>
      </div>
      <div class="facts">${statBadge(l)}</div>
    </article>`;
  }

  function tableHtml(rows) {
    const head = ["Type", "Bien", "Ville", "Zone", "P", "Surface", "Prix", "€/m²", "Livr./Vente", "Transport"];
    return `<table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>` +
      rows.map((l) => {
        const st = l.nearest_station;
        const d = st ? (st.walk_m ? `${Math.round(st.walk_m)} m à pied` : (st.crow_m ? `~${Math.round(st.crow_m)} m` : "")) : "";
        return `<tr data-id="${esc(l.id)}">
          <td><span class="kind ${esc(l.kind)}">${l.kind === "neuf" ? "Neuf" : "Vendu"}</span></td>
          <td class="name">${esc(l.name || "—")}</td>
          <td>${esc(l.city || "—")}</td>
          <td>${esc(l.zone_abc || "—")}</td>
          <td class="num">${l.rooms || "—"}</td>
          <td class="num">${l.surface ? area(l.surface) : "—"}</td>
          <td class="num">${money(l.price)}</td>
          <td class="num">${l.eur_m2 ? nf.format(l.eur_m2) : "—"}</td>
          <td>${esc(l.delivery_label || l.sale_date || "—")}</td>
          <td>${st ? esc(`${st.mode} ${st.line || ""} ${d}`) : "—"}</td>
        </tr>`;
      }).join("") + "</tbody></table>";
  }

  function render(data) {
    const box = $("#results");
    box.className = "results " + state.view;
    if (!data.results.length) {
      box.innerHTML = `<div class="empty"><h3>Aucun bien ne correspond</h3>
        <p>Élargissez un critère, ou activez « Garder les biens sans la donnée filtrée » :<br>
        beaucoup d'annonces ne publient ni la surface ni le prix par typologie.</p></div>`;
    } else if (state.view === "table") {
      box.innerHTML = tableHtml(data.results);
    } else {
      box.innerHTML = data.results.map(cardHtml).join("");
    }

    const s = data.stats || {};
    const parts = [`<b>${nf.format(data.total)}</b> bien${data.total > 1 ? "s" : ""}`];
    if (s.by_kind) {
      const bits = [];
      if (s.by_kind.neuf) bits.push(`${nf.format(s.by_kind.neuf)} neuf`);
      if (s.by_kind.ancien) bits.push(`${nf.format(s.by_kind.ancien)} vendu`);
      if (bits.length) parts.push(bits.join(" · "));
    }
    if (s.eur_m2) parts.push(`€/m² médian <b>${nf.format(s.eur_m2.median)}</b> <span style="opacity:.6">(${nf.format(s.eur_m2.min)}–${nf.format(s.eur_m2.max)})</span>`);
    if (s.surface) parts.push(`surface médiane <b>${nf.format(s.surface.median)}</b> m²`);
    $("#statline").innerHTML = parts.join('<span class="sep">·</span>');

    renderPager(data);
    if (data.facets) renderFacets(data.facets);
  }

  function renderFacets(f) {
    const fill = (sel, list, attr, key, label) => {
      const box = $(sel);
      if (!box) return;
      box.innerHTML = (list || []).map((x) =>
        `<button type="button" class="chip" data-${attr}="${esc(key(x))}"
          aria-pressed="${state[label].has(key(x)) ? "true" : "false"}">${esc(x.value)}<span class="n">${nf.format(x.count)}</span></button>`
      ).join("");
    };
    fill("#deptChips", f.dept, "dept", (x) => x.value, "depts");
    fill("#fiscalChips", f.fiscal, "fiscal", (x) => x.value, "fiscal");
  }

  function renderPager(data) {
    const nav = $("#pager");
    if (data.pages <= 1) { nav.innerHTML = ""; return; }
    const cur = data.page, last = data.pages;
    const nums = new Set([1, last, cur, cur - 1, cur + 1, cur - 2, cur + 2]);
    const list = [...nums].filter((n) => n >= 1 && n <= last).sort((a, b) => a - b);
    let html = `<button data-page="${cur - 1}" ${cur === 1 ? "disabled" : ""}>‹</button>`;
    let prev = 0;
    for (const n of list) {
      if (n - prev > 1) html += `<button disabled>…</button>`;
      html += `<button data-page="${n}" aria-current="${n === cur}">${n}</button>`;
      prev = n;
    }
    html += `<button data-page="${cur + 1}" ${cur === last ? "disabled" : ""}>›</button>`;
    nav.innerHTML = html;
  }

  function banner(msg, isError) {
    const b = $("#banner");
    if (!msg) { b.hidden = true; return; }
    b.hidden = false;
    b.className = "banner" + (isError ? " err" : "");
    b.textContent = msg;
  }

  /* ---------------------------------------------------------------- fetch */

  let timer = null;
  function search(resetPage) {
    if (resetPage) state.page = 1;
    clearTimeout(timer);
    timer = setTimeout(run, 160);
  }

  async function run() {
    const p = collect();
    applyToUrl(p);
    activeChips(p);
    const seq = ++state.seq;
    try {
      const res = await fetch("/api/search?" + new URLSearchParams(p));
      const data = await res.json();
      if (seq !== state.seq) return;         // a newer search already answered
      if (!res.ok) { banner(data.error || "Erreur", true); return; }
      banner(kindNotice(p));
      state.last = data;
      render(data);
    } catch (err) {
      if (seq === state.seq) banner("Le serveur ne répond pas : " + err.message, true);
    }
  }

  function kindNotice(p) {
    if (p.kind === "ancien") return "Ventes DVF : prix réellement enregistrés, avec quelques mois de décalage. Ce sont des références de prix, pas des biens à vendre.";
    if (p.kind === "neuf") return "";
    return "";
  }

  /* --------------------------------------------------------------- drawer */

  async function openDrawer(id) {
    const drawer = $("#drawer");
    drawer.hidden = false;
    $("#drawerBody").innerHTML = `<p class="sub">Chargement…</p>`;
    const [one, cmp] = await Promise.all([
      fetch(`/api/listing/${id}`).then((r) => r.json()).catch(() => null),
      fetch(`/api/comparables/${id}`).then((r) => r.json()).catch(() => ({ comparables: [] })),
    ]);
    if (!one || !one.listing) { $("#drawerBody").innerHTML = `<p class="sub">Introuvable.</p>`; return; }
    const l = one.listing;

    const kv = [
      ["Type", l.kind === "neuf" ? "Programme neuf (prix affiché)" : "Vente enregistrée (DVF)"],
      ["Prix", money(l.price)],
      ["Surface", l.surface ? area(l.surface) + (l.surface_is_carrez ? " (Carrez)" : "") : "non publiée"],
      ["€/m²", l.eur_m2 ? nf.format(l.eur_m2) + " €" : "non calculable"],
      ["Pièces", l.rooms || "—"],
      ["Étage", l.floor || "—"],
      ["Exposition", l.exposure || "—"],
      ["Adresse", [l.address, l.postcode, l.city].filter(Boolean).join(", ") || "—"],
      ["Précision adresse", l.address_precision || "—"],
      ["Zonage", l.zone_abc || "—"],
      ["Promoteur", l.developer || "—"],
      ["Livraison", l.delivery_label || "—"],
      ["Date de vente", l.sale_date || "—"],
      ["Dispositifs", (l.fiscal || []).join(", ") || "—"],
      ["Équipements", (l.features || []).join(", ") || "—"],
      ["Cuisine", l.kitchen_hint || "—"],
      ["Source", l.source],
    ].filter(([, v]) => v && v !== "—" || ["Prix", "Surface", "€/m²"].includes(v));

    const stations = (l.stations || []).slice(0, 6).map((s) => {
      const d = s.walk_m ? `${Math.round(s.walk_m)} m à pied · ${Math.round(s.walk_min || 0)} min`
        : (s.crow_m ? `~${Math.round(s.crow_m)} m à vol d'oiseau` : "—");
      return `<div class="station"><span class="ln">${esc(s.mode)} ${esc(s.line || "")} — ${esc(s.name)}</span><span class="d">${esc(d)}</span></div>`;
    }).join("");

    const comparables = (cmp.comparables || []);
    const cmpHtml = comparables.length
      ? `<table class="cmp">${comparables.slice(0, 8).map((c) => `<tr>
            <td>${esc(c.sale_date || "")}</td><td>${c.rooms || "?"}p</td>
            <td class="num">${area(c.surface)}</td>
            <td class="num">${money(c.price)}</td>
            <td class="num"><b>${c.eur_m2 ? nf.format(c.eur_m2) : "—"}</b></td>
            <td class="num" style="color:var(--ink-3)">${c.distance_m} m</td></tr>`).join("")}</table>`
      : `<p class="note">Aucune vente comparable dans l'index à moins de 1,5 km. Chargez plus d'années DVF pour densifier la référence.</p>`;

    const median = comparables.length
      ? Math.round(comparables.map((c) => c.eur_m2).filter(Boolean).sort((a, b) => a - b)[Math.floor(comparables.filter((c) => c.eur_m2).length / 2)] || 0)
      : 0;
    const verdict = (l.eur_m2 && median)
      ? `<p class="note">Ce bien est à <b>${nf.format(l.eur_m2)} €/m²</b>, contre <b>${nf.format(median)} €/m²</b> médian pour les ventes proches (${comparables.length} transactions). Écart : <b>${l.eur_m2 > median ? "+" : ""}${Math.round((l.eur_m2 / median - 1) * 100)} %</b>.</p>`
      : "";

    $("#drawerBody").innerHTML = `
      <h2 id="dTitle">${esc(l.name || "Sans nom")}</h2>
      <div class="sub">${esc([l.city, l.dept && `(${l.dept})`].filter(Boolean).join(" "))}</div>
      ${l.photos && l.photos.length ? `<div class="gallery">${l.photos.slice(0, 6).map((u) => `<img src="${esc(u)}" alt="" loading="lazy">`).join("")}</div>` : ""}
      <dl class="kv">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${l.notes ? `<p class="note">${esc(l.notes)}</p>` : ""}
      <h4>Transports à proximité</h4><div class="stations">${stations || '<p class="note">Pas de gare indexée à proximité.</p>'}</div>
      <h4>Ventes comparables (DVF)</h4>${verdict}${cmpHtml}
      <div class="links">
        ${l.url ? `<a class="primary" href="${esc(l.url)}" target="_blank" rel="noopener">Voir l'annonce</a>` : ""}
        ${l.plan_url ? `<a href="${esc(l.plan_url)}" target="_blank" rel="noopener">Plan (public)</a>` : ""}
        ${l.lat ? `<a href="https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lon}#map=17/${l.lat}/${l.lon}" target="_blank" rel="noopener">Voir sur la carte</a>` : ""}
      </div>`;
  }

  /* ----------------------------------------------------------------- csv */

  function exportCsv() {
    const data = state.last;
    if (!data || !data.results.length) return;
    const cols = ["kind", "name", "city", "dept", "zone_abc", "rooms", "surface",
      "price", "eur_m2", "delivery_label", "sale_date", "address", "source", "url"];
    const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [cols.join(",")];
    for (const r of data.results) lines.push(cols.map((c) => cell(r[c])).join(","));
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `immo-search-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* -------------------------------------------------------------- wiring */

  function toggleChip(btn, key, attr) {
    const value = btn.dataset[attr];
    if (state[key].has(value)) state[key].delete(value); else state[key].add(value);
    btn.setAttribute("aria-pressed", state[key].has(value) ? "true" : "false");
    search(true);
  }

  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) {
      if (chip.dataset.rooms !== undefined) return toggleChip(chip, "rooms", "rooms");
      if (chip.dataset.mode !== undefined) return toggleChip(chip, "modes", "mode");
      if (chip.dataset.zone !== undefined) return toggleChip(chip, "zones", "zone");
      if (chip.dataset.dept !== undefined) return toggleChip(chip, "depts", "dept");
      if (chip.dataset.fiscal !== undefined) return toggleChip(chip, "fiscal", "fiscal");
      if (chip.dataset.feature !== undefined) return toggleChip(chip, "features", "feature");
    }
    const clear = e.target.closest("[data-clear]");
    if (clear) {
      const key = clear.dataset.clear;
      const form = $("#filters");
      if (form.elements[key]) {
        const el = form.elements[key];
        if (el.type === "checkbox") el.checked = false; else el.value = "";
      }
      if (key === "kind") $("#kAll").checked = true;
      ({ mode: "modes", zone: "zones", dept: "depts", fiscal: "fiscal", feature: "features" })[key]
        && state[({ mode: "modes", zone: "zones", dept: "depts", fiscal: "fiscal", feature: "features" })[key]].clear();
      if (key === "rooms_min" || key === "rooms_max") state.rooms.clear();
      syncChips();
      return search(true);
    }
    const pageBtn = e.target.closest("[data-page]");
    if (pageBtn && !pageBtn.disabled) { state.page = Number(pageBtn.dataset.page); return run(); }

    const row = e.target.closest("[data-id]");
    if (row) return openDrawer(row.dataset.id);

    if (e.target.closest("[data-close]")) { $("#drawer").hidden = true; return; }
    if (e.target.id === "toggleFilters") $("#sidebar").classList.toggle("open");
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") $("#drawer").hidden = true;
    if (e.key === "Enter" && e.target.closest(".card")) openDrawer(e.target.dataset.id);
  });

  $("#filters").addEventListener("input", () => search(true));
  $("#filters").addEventListener("change", () => search(true));
  $("#sort").addEventListener("change", (e) => {
    [state.sort, state.order] = e.target.value.split("|");
    search(true);
  });
  $$("input[name=view]").forEach((r) => r.addEventListener("change", () => {
    state.view = $("input[name=view]:checked").value;
    if (state.last) render(state.last);
  }));
  $("#export").addEventListener("click", exportCsv);
  $("#reset").addEventListener("click", () => {
    $("#filters").reset();
    ["rooms", "modes", "zones", "depts", "fiscal", "features"].forEach((k) => state[k].clear());
    syncChips();
    search(true);
  });
  $("#brief").addEventListener("click", () => {
    $("#filters").reset();
    ["rooms", "modes", "zones", "depts", "fiscal", "features"].forEach((k) => state[k].clear());
    $("#kNeuf").checked = true;
    state.rooms.add("4");
    state.modes.add("RER");
    state.zones.add("abis"); state.zones.add("a");
    $("#surface_min").value = "80";
    $("#price_max").value = "425000";
    $("#eur_m2_max").value = "5300";
    $("#walk_max_m").value = "450";
    $("#delivery_from").value = "T4 2027";
    $("#delivery_to").value = "2029";
    syncChips();
    search(true);
  });

  /* ------------------------------------------------------------------ init */

  (async function init() {
    try {
      const meta = await fetch("/api/meta").then((r) => r.json());
      state.meta = meta;
      const n = meta.by_kind || {};
      $("#brandMeta").textContent =
        `${nf.format(meta.count || 0)} biens · ${nf.format(n.neuf || 0)} neuf · ${nf.format(n.ancien || 0)} ventes`;
      if (meta.facets) renderFacets(meta.facets);
    } catch {
      $("#brandMeta").textContent = "index non chargé";
    }
    restoreFromUrl();
    run();
  })();
})();
