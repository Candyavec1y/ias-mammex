/* MAMMEX — interface expert (éditeur de la base de connaissances) */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o));

const S = {
  jeton: null,
  auteur: null,
  base: null, // base active (enregistrée)
  draft: null, // copie en cours d'édition
  versions: [],
  cas: [],
  tab: "regles",
  niveau: "tous",
  rapport: null,
  essai: null,
  diffs: {},
  fzTest: {},
  dirty: false,
};

const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* navigation privée */ } },
  del(k) { try { sessionStorage.removeItem(k); } catch { /* idem */ } },
};

/* ------------------------------------------------------------------ outils */
async function api(url, data) {
  const opts = { headers: { "Content-Type": "application/json", "X-Jeton": S.jeton || "" } };
  if (data !== undefined) Object.assign(opts, { method: "POST", body: JSON.stringify(data) });
  let r;
  try {
    r = await fetch(url, opts);
  } catch {
    throw new Error("Le serveur MAMMEX ne répond pas. Vérifiez que la fenêtre de lancement est ouverte.");
  }
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) {
    deconnecter();
    throw new Error(j.erreur || "Session expirée.");
  }
  if (!r.ok) {
    const e = new Error(j.erreur || `Erreur ${r.status}`);
    e.donnees = j;
    throw e;
  }
  return j;
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

function fr(x, n = 2) {
  return x === null || x === undefined || x === "" ? "—" : Number(x).toFixed(n).replace(".", ",");
}

function setPath(obj, path, val) {
  const k = path.split(".");
  let o = obj;
  for (let i = 0; i < k.length - 1; i++) {
    const key = /^\d+$/.test(k[i]) ? +k[i] : k[i];
    if (o[key] === undefined || o[key] === null) o[key] = /^\d+$/.test(k[i + 1]) ? [] : {};
    o = o[key];
  }
  const last = /^\d+$/.test(k.at(-1)) ? +k.at(-1) : k.at(-1);
  if (val === undefined) delete o[last];
  else o[last] = val;
}

function marquer() {
  S.dirty = JSON.stringify(S.draft) !== JSON.stringify(S.base);
  $("#dirty").classList.toggle("hidden", !S.dirty);
  $("#btn-save").disabled = !S.dirty;
  $("#btn-reset").disabled = !S.dirty;
}

/* ------------------------------------------------------------------ session */
function deconnecter() {
  S.jeton = null;
  store.del("se-jeton");
  store.del("se-auteur");
  $("#editor-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
  $("#who").classList.add("hidden");
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/expert/connexion", { nom: $("#lg-nom").value, code: $("#lg-code").value });
    S.jeton = r.jeton;
    S.auteur = r.auteur;
    store.set("se-jeton", r.jeton);
    store.set("se-auteur", r.auteur);
    await ouvrir();
  } catch (err) {
    toast(err.message);
  }
});

async function ouvrir() {
  const r = await api("/api/expert/base");
  S.base = r.base;
  S.draft = clone(r.base);
  S.versions = r.versions;
  if (!S.cas.length) S.cas = await api("/api/cas");
  $("#login-view").classList.add("hidden");
  $("#editor-view").classList.remove("hidden");
  $("#who").textContent = S.auteur;
  $("#who").classList.remove("hidden");
  $("#ver-pill").textContent = `Version active : v${S.base.meta?.version ?? "?"}`;
  marquer();
  rendre();
}

/* ------------------------------------------------------------------ onglets */
const TABS = [
  ["regles", "Règles", () => S.draft.regles.length],
  ["faits", "Faits et questions", () => S.draft.questions.length + S.draft.faits_intermediaires.length],
  ["floues", "Variables floues", () => S.draft.variables_floues.length],
  ["controle", "Méta-règles et heuristiques", () => S.draft.meta_regles.length + S.draft.heuristiques.length],
  ["parametres", "Paramètres", null],
  ["verification", "Vérification", null],
  ["versions", "Versions", () => S.versions.length],
];

function rendre() {
  $("#tabs").innerHTML = TABS.map(([id, lib, n]) =>
    `<button class="tab ${S.tab === id ? "active" : ""}" role="tab" aria-selected="${S.tab === id}" data-tab="${id}">${lib}${n ? `<span class="count">${n()}</span>` : ""}</button>`
  ).join("");
  $$("#tabs [data-tab]").forEach((b) => b.addEventListener("click", () => { S.tab = b.dataset.tab; rendre(); }));
  const f = { regles: rendreRegles, faits: rendreFaits, floues: rendreFloues, controle: rendreControle, parametres: rendreParametres, verification: rendreVerification, versions: rendreVersions }[S.tab];
  $("#panel").innerHTML = f();
  apresRendu();
}

/* ------------------------------------------------------------------ champs génériques */
const opt = (v, lib, sel) => `<option value="${esc(v)}" ${String(v) === String(sel) ? "selected" : ""}>${esc(lib)}</option>`;
function champ(lib, path, val, { t = "text", cls = "", attrs = "", rerender = false } = {}) {
  const rr = rerender ? " data-rerender" : "";
  let input;
  if (t === "textarea") input = `<textarea data-p="${path}" data-t="text"${rr} ${attrs}>${esc(val)}</textarea>`;
  else if (t === "num") input = `<input type="number" step="0.05" data-p="${path}" data-t="num"${rr} value="${esc(val)}" ${attrs}>`;
  else if (t === "list") input = `<input data-p="${path}" data-t="list"${rr} value="${esc((val || []).join(", "))}" ${attrs}>`;
  else if (t === "json") input = `<textarea class="mono" data-p="${path}" data-t="json"${rr} ${attrs}>${esc(val === undefined ? "" : JSON.stringify(val))}</textarea>`;
  else input = `<input data-p="${path}" data-t="text"${rr} value="${esc(val)}" ${attrs}>`;
  return `<div class="field ${cls}"><label>${lib}</label>${input}</div>`;
}
function select(lib, path, val, options, { cls = "", rerender = false, t = "text" } = {}) {
  return `<div class="field ${cls}"><label>${lib}</label><select data-p="${path}" data-t="${t}"${rerender ? " data-rerender" : ""}>${options.map(([v, l]) => opt(v, l, val)).join("")}</select></div>`;
}

/* ------------------------------------------------------------------ règles */
function factsDispo() {
  const d = S.draft;
  const l = [];
  for (const q of d.questions) {
    if (q.type === "oui_non") l.push([q.id, q.libelle || q.texte]);
    if (q.type === "choix") l.push([`${q.id} = ${(q.options || []).map((o) => o.id).join(" | ")}`, q.libelle || q.texte]);
  }
  for (const v of d.variables_floues) for (const e of v.ensembles) l.push([`${v.id} EST ${e.id}`, `${v.libelle} est ${e.libelle} (variable floue)`]);
  for (const f of d.faits_intermediaires) l.push([f.id, f.libelle + " (fait intermédiaire)"]);
  return l;
}

function rendreRegles() {
  const d = S.draft;
  const filtres = [["tous", "Toutes"], ["1", "Niveau 1 · interprétation"], ["2", "Niveau 2 · diagnostic"]];
  const regles = d.regles.map((r, i) => [r, i]).filter(([r]) => S.niveau === "tous" || String(r.niveau) === S.niveau);
  const cartes = regles.map(([r, i]) => {
    const p = `regles.${i}`;
    const concl = r.niveau === 2 ? d.diagnostics.map((x) => [x.id, x.libelle]) : d.faits_intermediaires.map((x) => [x.id, x.libelle]);
    if (!concl.some(([v]) => v === r.conclusion)) concl.unshift([r.conclusion ?? "", `${r.conclusion ?? "—"} (inconnu)`]);
    return `<div class="card rule ${r.actif === false ? "off" : ""}">
      <div class="rule-head">
        <input class="input rid" aria-label="Identifiant" data-p="${p}.id" data-t="text" value="${esc(r.id)}">
        <select class="input" style="width:auto" aria-label="Niveau" data-p="${p}.niveau" data-t="num" data-rerender>${opt(1, "Niveau 1", r.niveau)}${opt(2, "Niveau 2", r.niveau)}</select>
        <label class="inline-check"><input type="checkbox" data-p="${p}.actif" data-t="bool" data-rerender ${r.actif === false ? "" : "checked"}> active</label>
        <span style="flex:1"></span>
        <button class="btn small ghost danger" data-act="del-regle" data-i="${i}">Supprimer</button>
      </div>
      <div class="rule-grid">
        <div class="field premise full"><label>SI (prémisse)</label>
          <input data-p="${p}.premisse" data-t="text" data-premisse data-niveau="${r.niveau}" value="${esc(r.premisse)}" spellcheck="false">
          <div class="check" data-check="${i}"></div></div>
        ${champ("Commentaire", `${p}.commentaire`, r.commentaire)}
        ${select("ALORS", `${p}.conclusion`, r.conclusion, concl)}
        ${champ("CF de la règle", `${p}.cf`, r.cf, { t: "num", attrs: 'min="0" max="1"' })}
        ${r.niveau === 2 ? champ("Recommandation", `${p}.recommandation`, r.recommandation, { cls: "full" }) : ""}
        ${r.niveau === 2 ? champ("Recommandation si un résultat de biopsie est déjà connu (facultatif)", `${p}.recommandation_si_biopsie`, r.recommandation_si_biopsie, { cls: "full" }) : ""}
      </div></div>`;
  }).join("");
  return `
    <div class="ed-bar" style="margin-bottom:10px">
      ${filtres.map(([v, l]) => `<button class="btn small ${S.niveau === v ? "primary" : ""}" data-act="filtre" data-v="${v}">${l}</button>`).join("")}
      <span class="spacer"></span>
      <button class="btn small" data-act="add-regle">+ Ajouter une règle</button>
    </div>
    <details class="card card-pad" style="margin-bottom:12px;padding-top:12px;padding-bottom:12px">
      <summary style="cursor:pointer;font-weight:600">Syntaxe des prémisses et faits utilisables</summary>
      <p class="muted" style="font-size:13.5px">Mots-clés en majuscules : <b>ET</b> (minimum), <b>OU</b> (maximum), <b>NON</b> (1 − CF), <b>EST</b> (variable floue),
        <b>=</b> (réponse à choix), parenthèses. ET est prioritaire sur OU. Le niveau 1 lit les réponses du médecin ; le niveau 2 lit les faits intermédiaires et la biopsie.</p>
      <table class="trace"><tbody>${factsDispo().map(([k, l]) => `<tr><td class="mono">${esc(k)}</td><td>${esc(l)}</td></tr>`).join("")}</tbody></table>
    </details>
    ${cartes || '<div class="empty">Aucune règle.</div>'}`;
}

let minuteurs = {};
async function analyser(input) {
  const i = input.dataset.p.split(".")[1];
  const box = $(`[data-check="${i}"]`);
  if (!box) return;
  try {
    const r = await api("/api/expert/analyser", { base: S.draft, premisse: input.value, niveau: +input.dataset.niveau });
    if (!r.ok) box.innerHTML = `<span class="ko">✗ ${esc(r.erreurs.join(" · "))}</span>`;
    else if (r.avertissements.length) box.innerHTML = `<span class="warn">⚠ ${esc(r.avertissements.join(" · "))}</span>`;
    else box.innerHTML = `✓ <span class="lisible">SI ${esc(r.lisible || r.normalisee)}</span>`;
    box.className = "check " + (!r.ok ? "ko" : r.avertissements.length ? "warn" : "ok");
  } catch (e) {
    box.textContent = e.message;
  }
}

/* ------------------------------------------------------------------ faits et questions */
function rendreFaits() {
  const d = S.draft;
  const etapes = d.etapes.map((e) => [e.id, e.libelle]);
  const qs = d.questions.map((q, i) => {
    const p = `questions.${i}`;
    const opts = (q.options || []).map((o) => `${o.id} : ${o.libelle}`).join("\n");
    const conditions = {};
    if (q.masquer_si) conditions.masquer_si = q.masquer_si;
    if (q.afficher_si) conditions.afficher_si = q.afficher_si;
    return `<div class="card rule">
      <div class="rule-head">
        <input class="input rid" style="width:200px" aria-label="Identifiant" data-p="${p}.id" data-t="text" value="${esc(q.id)}">
        <span class="muted" style="font-size:13px">${esc(q.libelle || "")}</span>
        <span style="flex:1"></span>
        <button class="btn small ghost danger" data-act="del-question" data-i="${i}">Supprimer</button>
      </div>
      <div class="subgrid">
        ${select("Étape", `${p}.etape`, q.etape, etapes)}
        ${select("Moment", `${p}.phase`, q.phase || "recueil", [["recueil", "Recueil (toujours posée)"], ["chainage_arriere", "Chaînage arrière (si utile, H4)"]])}
        ${select("Type de réponse", `${p}.type`, q.type, [["oui_non", "Oui / Non / Je ne sais pas"], ["nombre", "Nombre"], ["choix", "Choix"]], { rerender: true })}
        ${q.type === "oui_non" ? select("Certitude après un Oui", `${p}.certitude`, q.certitude === false ? "false" : "true", [["true", "Demandée"], ["false", "Non demandée"]], { t: "boolstr" }) : ""}
        ${q.type === "nombre" ? champ("Unité", `${p}.unite`, q.unite) + champ("Min", `${p}.min`, q.min, { t: "num" }) + champ("Max", `${p}.max`, q.max, { t: "num" }) : ""}
        ${champ("Libellé court (rapport)", `${p}.libelle`, q.libelle)}
      </div>
      ${champ("Question posée au médecin", `${p}.texte`, q.texte)}
      ${champ("Aide (facultatif)", `${p}.aide`, q.aide)}
      ${q.type === "choix" ? `<div class="subgrid" style="grid-template-columns:1fr 1fr">
        <div class="field"><label>Options (une par ligne : identifiant : libellé)</label><textarea data-p="${p}.options" data-t="options">${esc(opts)}</textarea></div>
        ${champ("Valeur si la question parente vaut Non", `${p}.valeur_si_parent_non`, q.valeur_si_parent_non)}</div>` : ""}
      <div class="field"><label>Conditions d'affichage (JSON, facultatif) — ex. {"masquer_si": {"non": ["nodule_dur"]}}</label>
        <textarea class="mono" data-p="${p}" data-t="conditions" style="min-height:40px">${esc(Object.keys(conditions).length ? JSON.stringify(conditions) : "")}</textarea></div>
    </div>`;
  }).join("");
  const inter = d.faits_intermediaires.map((f, i) => `<div class="subgrid" style="grid-template-columns:200px 1fr 160px 200px auto;align-items:end">
      ${champ("Identifiant", `faits_intermediaires.${i}.id`, f.id)}
      ${champ("Libellé", `faits_intermediaires.${i}.libelle`, f.libelle)}
      ${select("Groupe", `faits_intermediaires.${i}.groupe`, f.groupe, etapes)}
      ${select("Fait opposé", `faits_intermediaires.${i}.oppose`, f.oppose || "", [["", "—"], ...d.faits_intermediaires.filter((x) => x.id !== f.id).map((x) => [x.id, x.libelle])])}
      <button class="btn small ghost danger" style="margin-bottom:2px" data-act="del-inter" data-i="${i}">✕</button></div>`).join("");
  const diags = d.diagnostics.map((x, i) => `<div class="subgrid" style="grid-template-columns:200px 1fr 200px auto;align-items:end">
      ${champ("Identifiant", `diagnostics.${i}.id`, x.id)}
      ${champ("Libellé", `diagnostics.${i}.libelle`, x.libelle)}
      ${select("Gravité (couleur)", `diagnostics.${i}.gravite`, x.gravite, [["rouge", "Rouge · grave"], ["orange", "Orange · à explorer"], ["vert", "Vert · rassurant"]])}
      <button class="btn small ghost danger" style="margin-bottom:2px" data-act="del-diag" data-i="${i}">✕</button></div>`).join("");
  return `
    <p class="section-title">Faits intermédiaires (conclusions du niveau 1)</p>
    <div class="card card-pad" style="margin-bottom:8px">${inter}<button class="btn small" style="margin-top:10px" data-act="add-inter">+ Ajouter un fait intermédiaire</button></div>
    <p class="section-title" style="margin-top:20px">Diagnostics (conclusions du niveau 2)</p>
    <div class="card card-pad" style="margin-bottom:8px">${diags}<button class="btn small" style="margin-top:10px" data-act="add-diag">+ Ajouter un diagnostic</button></div>
    <div class="ed-bar" style="margin-top:20px"><p class="section-title" style="margin:0">Questions posées au médecin (dans l'ordre de la consultation)</p><span class="spacer"></span>
      <button class="btn small" data-act="add-question">+ Ajouter une question</button></div>
    ${qs}`;
}

/* ------------------------------------------------------------------ variables floues */
const FORMES = {
  croissante: { lib: "Croissante (rampe ↗)", mus: [0, 1], params: ["μ = 0 jusqu'à", "μ = 1 à partir de"] },
  decroissante: { lib: "Décroissante (rampe ↘)", mus: [1, 0], params: ["μ = 1 jusqu'à", "μ = 0 à partir de"] },
  triangle: { lib: "Triangulaire", mus: [0, 1, 0], params: ["μ = 0 jusqu'à", "μ = 1 au sommet", "μ = 0 à partir de"] },
  trapeze: { lib: "Trapézoïdale", mus: [0, 1, 1, 0], params: ["μ = 0 jusqu'à", "μ = 1 de", "μ = 1 jusqu'à", "μ = 0 à partir de"] },
  points: { lib: "Points libres (linéaire par morceaux)" },
};
const COULEURS_FZ = ["var(--accent)", "#6a1b9a", "#1565c0", "#00897b", "#ef6c00"];

// points [[x, μ], …] d'un ensemble ; l'ancien format debut / fin est une rampe croissante
const ptsEns = (e) => (e.points?.length ? e.points.map(([x, m]) => [Number(x), Number(m)]) : [[Number(e.debut), 0], [Number(e.fin), 1]]);
const formeEns = (e) => (FORMES[e.forme] ? e.forme : e.points ? "points" : "croissante");
function muPts(x, pts) {
  if (x === null || x === undefined || x === "" || isNaN(x) || !pts.length) return null;
  if (x <= pts[0][0]) return pts[0][1];
  for (let k = 1; k < pts.length; k++) {
    const [x0, m0] = pts[k - 1], [x1, m1] = pts[k];
    if (x <= x1) return x1 === x0 ? m1 : m0 + ((m1 - m0) * (x - x0)) / (x1 - x0);
  }
  return pts.at(-1)[1];
}
function erreursEns(e) {
  const pts = ptsEns(e);
  if (pts.some(([x, m]) => isNaN(x) || isNaN(m))) return "Toutes les valeurs doivent être renseignées.";
  if (pts.length < 2) return "Au moins deux points sont nécessaires.";
  if (pts.some(([x], k) => k && x <= pts[k - 1][0])) return "Les abscisses doivent être strictement croissantes.";
  if (pts.some(([, m]) => m < 0 || m > 1)) return "μ doit être compris entre 0 et 1.";
  return "";
}
const nb = (x) => String(Math.round(x * 1000) / 1000).replace(".", ",");
function formule(e, unite) {
  const pts = ptsEns(e);
  if (erreursEns(e)) return "";
  const l = [`μ(x) = ${nb(pts[0][1])}  si x ≤ ${nb(pts[0][0])}`];
  for (let k = 1; k < pts.length; k++) {
    const [x0, m0] = pts[k - 1], [x1, m1] = pts[k], w = nb(x1 - x0);
    let f;
    if (m0 === m1) f = nb(m0);
    else if (m0 === 0 && m1 === 1) f = `(x − ${nb(x0)}) / ${w}`;
    else if (m0 === 1 && m1 === 0) f = `(${nb(x1)} − x) / ${w}`;
    else f = `${nb(m0)} ${m1 > m0 ? "+" : "−"} ${nb(Math.abs(m1 - m0))} × (x − ${nb(x0)}) / ${w}`;
    l.push(`μ(x) = ${f}  si ${nb(x0)} < x ≤ ${nb(x1)}`);
  }
  l.push(`μ(x) = ${nb(pts.at(-1)[1])}  si x > ${nb(pts.at(-1)[0])}`);
  return l.join("\n") + (unite ? `\n(x en ${unite})` : "");
}
function domaine(v) {
  const xs = v.ensembles.flatMap((e) => ptsEns(e).map(([x]) => x)).filter((x) => !isNaN(x));
  let lo = Number(v.min), hi = Number(v.max);
  if (v.min === undefined || v.min === "" || isNaN(lo)) lo = xs.length ? Math.min(...xs) - 10 : 0;
  if (v.max === undefined || v.max === "" || isNaN(hi)) hi = xs.length ? Math.max(...xs) + 10 : 100;
  if (hi <= lo) hi = lo + 1;
  return [lo, hi];
}
function svgFonction(v, testX) {
  const W = 560, H = 240, L = 40, R = 16, T = 14, B = 36;
  const [lo, hi] = domaine(v);
  const px = (x) => L + ((x - lo) / (hi - lo)) * (W - L - R);
  const py = (m) => T + (1 - m) * (H - T - B);
  const brut = (hi - lo) / 8, p10 = 10 ** Math.floor(Math.log10(brut));
  const pas = [1, 2, 5, 10].map((k) => k * p10).find((k) => k >= brut);
  let g = "";
  for (const m of [0, 0.5, 1]) g += `<line x1="${L}" x2="${W - R}" y1="${py(m)}" y2="${py(m)}" stroke="var(--line)" ${m ? 'stroke-dasharray="3 3"' : ""}/>
    <text x="${L - 8}" y="${py(m) + 4}" text-anchor="end" font-size="11" fill="var(--faint)">${nb(m)}</text>`;
  for (let x = Math.ceil(lo / pas) * pas; x <= hi + 1e-9; x += pas) g += `<line x1="${px(x)}" x2="${px(x)}" y1="${py(0)}" y2="${py(0) + 4}" stroke="var(--line-strong)"/>
    <text x="${px(x)}" y="${py(0) + 17}" text-anchor="middle" font-size="11" fill="var(--faint)">${nb(x)}</text>`;
  g += `<text x="${W - R}" y="${H - 3}" text-anchor="end" font-size="11" fill="var(--muted)">${esc(v.libelle || v.id)}${v.unite ? ` (${esc(v.unite)})` : ""}</text>
    <text x="${L - 8}" y="${T - 2}" text-anchor="end" font-size="11" fill="var(--muted)">μ</text>`;
  let courbes = "", test = "";
  v.ensembles.forEach((e, j) => {
    if (erreursEns(e)) return;
    const pts = ptsEns(e), c = COULEURS_FZ[j % COULEURS_FZ.length];
    const xs = [lo, ...pts.map(([x]) => x).filter((x) => x > lo && x < hi), hi];
    const ligne = xs.map((x) => `${px(x).toFixed(1)},${py(muPts(x, pts)).toFixed(1)}`).join(" ");
    courbes += `<polygon points="${px(lo)},${py(0)} ${ligne} ${px(hi)},${py(0)}" fill="${c}" opacity=".08"/>
      <polyline points="${ligne}" fill="none" stroke="${c}" stroke-width="2.2" stroke-linejoin="round"/>
      ${pts.filter(([x]) => x >= lo && x <= hi).map(([x, m]) => `<circle cx="${px(x)}" cy="${py(m)}" r="3.5" fill="#fff" stroke="${c}" stroke-width="2"/>`).join("")}`;
    const mu = muPts(testX, pts);
    if (mu !== null && testX >= lo && testX <= hi) test += `<circle cx="${px(testX)}" cy="${py(mu)}" r="5" fill="${c}"/>
      <text x="${px(testX) + 8}" y="${py(mu) - 6}" font-size="12" font-weight="600" fill="${c}">${nb(Math.round(mu * 100) / 100)}</text>`;
  });
  if (test) test = `<line x1="${px(testX)}" x2="${px(testX)}" y1="${py(0)}" y2="${py(1) - 6}" stroke="var(--text)" stroke-dasharray="4 3" opacity=".5"/>` + test;
  const legende = v.ensembles.map((e, j) => `<span><i style="background:${COULEURS_FZ[j % COULEURS_FZ.length]}"></i>${esc(e.libelle || e.id)}</span>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="fz-svg" role="img" aria-label="Fonctions d'appartenance de ${esc(v.libelle || v.id)}">${g}${courbes}${test}</svg>
    <div class="fz-legend">${legende}</div>`;
}
function resultatTest(v, x) {
  if (x === null || x === undefined || x === "" || isNaN(x)) return '<span class="muted">Saisissez une valeur pour lire les degrés d\'appartenance.</span>';
  return v.ensembles.filter((e) => !erreursEns(e)).map((e) => {
    const mu = muPts(Number(x), ptsEns(e));
    return `<span class="fz-res"><b>μ<sub>${esc(e.libelle || e.id)}</sub>(${nb(Number(x))}) = ${nb(Math.round(mu * 1000) / 1000)}</b> · ${Math.round(mu * 100)} %</span>`;
  }).join("");
}
function fzNum(lib, path, val, i, { step = 1, attrs = "" } = {}) {
  return `<div class="field"><label>${lib}</label><input type="number" step="${step}" data-p="${path}" data-t="num" data-fz="${i}" value="${esc(val)}" ${attrs}></div>`;
}

function rendreFloues() {
  const d = S.draft;
  // conversion silencieuse de l'ancien format (debut / fin) vers des points éditables
  for (const v of d.variables_floues) for (const e of v.ensembles) if (!e.points?.length) {
    e.points = ptsEns(e);
    e.forme = "croissante";
    delete e.debut;
    delete e.fin;
    marquer();
  }
  const nombres = d.questions.filter((q) => q.type === "nombre").map((q) => [q.id, `${q.libelle || q.texte} (${q.id})`]);
  const cartes = d.variables_floues.map((v, i) => {
    const p = `variables_floues.${i}`;
    const vars = nombres.some(([id]) => id === v.id) ? nombres : [[v.id, `${v.id} (question inconnue)`], ...nombres];
    const ensembles = v.ensembles.map((e, j) => {
      const pe = `${p}.ensembles.${j}`, f = formeEns(e), pts = ptsEns(e), c = COULEURS_FZ[j % COULEURS_FZ.length];
      const params = f === "points"
        ? `<table class="fz-pts"><thead><tr><th>x${v.unite ? ` (${esc(v.unite)})` : ""}</th><th>μ(x)</th><th></th></tr></thead><tbody>
            ${pts.map(([x, m], k) => `<tr>
              <td><input type="number" step="1" data-p="${pe}.points.${k}.0" data-t="num" data-fz="${i}" value="${esc(x)}" aria-label="x du point ${k + 1}"></td>
              <td><input type="number" step="0.05" min="0" max="1" data-p="${pe}.points.${k}.1" data-t="num" data-fz="${i}" value="${esc(m)}" aria-label="μ du point ${k + 1}"></td>
              <td><button class="btn small ghost danger" data-act="fz-del-pt" data-i="${i}" data-j="${j}" data-k="${k}" ${pts.length <= 2 ? "disabled" : ""} aria-label="Supprimer le point">✕</button></td></tr>`).join("")}
            </tbody></table>
            <button class="btn small ghost" data-act="fz-add-pt" data-i="${i}" data-j="${j}">+ Ajouter un point</button>`
        : `<div class="fz-params">${FORMES[f].params.map((lib, k) => fzNum(`${lib}${v.unite ? ` (${esc(v.unite)})` : ""}`, `${pe}.points.${k}.0`, pts[k]?.[0], i)).join("")}</div>`;
      return `<div class="fz-ens" style="--c:${c}">
        <div class="fz-ens-head"><i class="fz-dot"></i><b>Ensemble « ${esc(e.libelle || e.id)} »</b><span class="spacer"></span>
          <button class="btn small ghost danger" data-act="fz-del-ens" data-i="${i}" data-j="${j}" ${v.ensembles.length <= 1 ? "disabled" : ""}>Supprimer</button></div>
        <div class="fz-row">
          ${champ("Identifiant (utilisé dans les règles)", `${pe}.id`, e.id, { attrs: `data-fz="${i}" spellcheck="false"` })}
          ${champ("Libellé", `${pe}.libelle`, e.libelle, { attrs: `data-fz="${i}"` })}
          <div class="field"><label>Forme de la fonction</label><select data-p="${pe}.forme" data-t="text" data-fz-forme="${i}.${j}">
            ${Object.entries(FORMES).map(([id, x]) => opt(id, x.lib, f)).join("")}</select></div>
        </div>
        ${params}
        <div class="check ko" data-fz-err="${i}.${j}">${esc(erreursEns(e))}</div>
        <p class="fz-usage">Dans une prémisse : <span class="mono">${esc(v.id)} EST ${esc(e.id)}</span></p>
        <pre class="fz-formule" data-fz-formule="${i}.${j}">${esc(formule(e, v.unite))}</pre>
      </div>`;
    }).join("");
    const t = S.fzTest[i] ?? "";
    return `<div class="card fz-card">
      <div class="fz-top">
        ${select("Variable (question numérique)", `${p}.id`, v.id, vars, { rerender: true })}
        ${champ("Libellé", `${p}.libelle`, v.libelle, { attrs: `data-fz="${i}"` })}
        ${champ("Unité", `${p}.unite`, v.unite, { attrs: `data-fz="${i}"` })}
        ${fzNum("Axe : de", `${p}.min`, v.min ?? "", i)}
        ${fzNum("à", `${p}.max`, v.max ?? "", i)}
      </div>
      <div class="fz-body">
        <div class="fz-editors">${ensembles}
          <button class="btn small" data-act="fz-add-ens" data-i="${i}">+ Ajouter un ensemble flou</button></div>
        <div class="fz-side">
          <div class="fz-chart" data-fz-chart="${i}">${svgFonction(v, t === "" ? null : Number(t))}</div>
          <div class="fz-test">
            <label for="fz-test-${i}">Tester une valeur</label>
            <div class="fz-test-row"><input id="fz-test-${i}" type="number" step="1" data-fz-test="${i}" value="${esc(t)}" placeholder="${esc(v.unite || "valeur")}">
              <div data-fz-res="${i}">${resultatTest(v, t)}</div></div>
          </div>
        </div>
      </div>
    </div>`;
  }).join("");
  return `
    <p class="muted" style="font-size:13.5px;margin:0 0 14px;max-width:80ch">Une variable floue convertit une donnée numérique (l'âge, par exemple)
      en degré d'appartenance μ compris entre 0 et 1, utilisé comme facteur de certitude dans les prémisses (<span class="mono">age EST agee</span>).
      Choisissez une forme puis ses seuils, ou définissez librement la fonction point par point : μ est interpolé linéairement entre les points
      et reste constant avant le premier et après le dernier.</p>
    ${cartes || '<div class="empty">Aucune variable floue.</div>'}`;
}

// mise à jour en place (sans perdre le focus) du graphique, des formules et du test
function majFlou(i) {
  const v = S.draft.variables_floues[i];
  if (!v) return;
  const t = S.fzTest[i] ?? "";
  const ch = $(`[data-fz-chart="${i}"]`);
  if (ch) ch.innerHTML = svgFonction(v, t === "" ? null : Number(t));
  const res = $(`[data-fz-res="${i}"]`);
  if (res) res.innerHTML = resultatTest(v, t);
  v.ensembles.forEach((e, j) => {
    const f = $(`[data-fz-formule="${i}.${j}"]`);
    if (f) f.textContent = formule(e, v.unite);
    const er = $(`[data-fz-err="${i}.${j}"]`);
    if (er) er.textContent = erreursEns(e);
  });
}

// nouvelle forme : on régénère les points sur la plage actuelle
function changerForme(e, forme) {
  const xs = ptsEns(e).map(([x]) => x).filter((x) => !isNaN(x));
  let lo = xs.length ? Math.min(...xs) : 0, hi = xs.length ? Math.max(...xs) : 10;
  if (hi <= lo) hi = lo + 10;
  const r = (x) => (hi - lo >= 10 ? Math.round(x) : Math.round(x * 10) / 10);
  e.forme = forme;
  if (forme === "points") return;
  const n = FORMES[forme].mus.length;
  e.points = FORMES[forme].mus.map((m, k) => [r(lo + ((hi - lo) * k) / (n - 1)), m]);
}

/* ------------------------------------------------------------------ méta-règles et heuristiques */
const LIB_PARAM = {
  regles_histologie: "Règles d'histologie", fait_biopsie: "Fait « résultat de biopsie »", valeurs_sans_resultat: "Valeurs sans résultat",
  seuil: "Seuil", groupes: "Groupes à compléter", nombre_max_demandes: "Nombre maximal de demandes", conditions: "Conditions (OU)",
  regles_desactivees: "Règles désactivées", fait: "Fait surveillé", recommandation: "Recommandation ajoutée", ordre: "Ordre de test",
  seuil_retenue: "Seuil pour retenir une hypothèse", ordre_etapes: "Ordre des étapes", questions_conditionnees: "Questions soumises à H4",
};

function rendreParams(path, params) {
  const inter = S.draft.faits_intermediaires.map((f) => [f.id, f.libelle]);
  return Object.entries(params || {}).map(([k, v]) => {
    const p = `${path}.${k}`;
    const lib = esc(LIB_PARAM[k] || k);
    if (Array.isArray(v) && v.length && typeof v[0] === "object" && "fait" in v[0]) {
      return `<div class="param-row"><span>${lib}</span><div>${v.map((c, j) => `<div class="cond-row">
          <select class="input" data-p="${p}.${j}.fait" data-t="text">${inter.map(([a, b]) => opt(a, b, c.fait)).join("")}</select>
          <span>≥</span><input class="input" type="number" step="0.05" data-p="${p}.${j}.seuil" data-t="num" value="${esc(c.seuil)}">
          <button class="btn small ghost danger" data-act="del-cond" data-path="${p}" data-i="${j}">✕</button></div>`).join("")}
          <button class="btn small ghost" data-act="add-cond" data-path="${p}">+ condition</button></div></div>`;
    }
    if (Array.isArray(v)) return `<div class="param-row"><span>${lib}</span><input class="input" data-p="${p}" data-t="list" value="${esc(v.join(", "))}"></div>`;
    if (typeof v === "number") return `<div class="param-row"><span>${lib}</span><input class="input" style="max-width:120px" type="number" step="0.05" data-p="${p}" data-t="num" value="${esc(v)}"></div>`;
    if (k === "fait") return `<div class="param-row"><span>${lib}</span><select class="input" data-p="${p}" data-t="text">${inter.map(([a, b]) => opt(a, b, v)).join("")}</select></div>`;
    return `<div class="param-row"><span>${lib}</span><input class="input" data-p="${p}" data-t="text" value="${esc(v)}"></div>`;
  }).join("");
}

function rendreControle() {
  const d = S.draft;
  const mr = d.meta_regles.map((m, i) => `<div class="card rule ${m.actif === false ? "off" : ""}">
      <div class="rule-head"><span class="rid">${esc(m.id)}</span>
        <label class="inline-check"><input type="checkbox" data-p="meta_regles.${i}.actif" data-t="bool" data-rerender ${m.actif === false ? "" : "checked"}> active</label></div>
      <div class="subgrid" style="grid-template-columns:1fr 2fr">${champ("SI (état du raisonnement)", `meta_regles.${i}.si`, m.si)}${champ("ALORS (action de contrôle)", `meta_regles.${i}.alors`, m.alors)}</div>
      ${m.parametres ? `<div style="margin-top:8px">${rendreParams(`meta_regles.${i}.parametres`, m.parametres)}</div>` : '<p class="muted" style="font-size:13px;margin:8px 0 0">Comportement fixe du moteur, sans paramètre.</p>'}
    </div>`).join("");
  const h = d.heuristiques.map((x, i) => `<div class="card rule">
      <div class="rule-head"><span class="rid">${esc(x.id)}</span><strong>${esc(x.nom)}</strong></div>
      ${champ("Effet", `heuristiques.${i}.effet`, x.effet)}
      <div style="margin-top:8px">${rendreParams(`heuristiques.${i}.parametres`, x.parametres)}</div>
    </div>`).join("");
  return `<p class="muted" style="font-size:14px;margin:0 0 12px">Une méta-règle choisit quelles règles ont le droit de jouer ; une heuristique choisit entre plusieurs règles qui jouent déjà.
      Le texte SI / ALORS est affiché aux utilisateurs ; le comportement dépend des paramètres.</p>
    <p class="section-title">Méta-règles</p>${mr}
    <p class="section-title" style="margin-top:20px">Heuristiques</p>${h}`;
}

/* ------------------------------------------------------------------ paramètres */
function rendreParametres() {
  const p = S.draft.parametres;
  return `<div class="card card-pad">
    <p class="section-title">Facteurs de certitude</p>
    <div class="param-row"><span>Seuil d'activation des règles</span><input class="input" style="max-width:120px" type="number" step="0.05" data-p="parametres.seuil_activation" data-t="num" value="${esc(p.seuil_activation)}"></div>
    ${Object.entries(p.certitudes).map(([k, v]) => `<div class="param-row"><span>CF d'un Oui « ${esc(k)} »</span><input class="input" style="max-width:120px" type="number" step="0.05" data-p="parametres.certitudes.${k}" data-t="num" value="${esc(v)}"></div>`).join("")}
    <p class="section-title" style="margin-top:20px">Lecture du CF affichée au médecin</p>
    ${p.lecture_cf.map((l, i) => `<div class="param-row"><span>À partir de <input class="input" style="width:90px;display:inline-block" type="number" step="0.05" data-p="parametres.lecture_cf.${i}.min" data-t="num" value="${esc(l.min)}"></span>
      <input class="input" data-p="parametres.lecture_cf.${i}.texte" data-t="text" value="${esc(l.texte)}"></div>`).join("")}
    <p class="section-title" style="margin-top:20px">Description</p>
    ${champ("Nom du système", "meta.nom", S.draft.meta.nom)}
    ${champ("Description", "meta.description", S.draft.meta.description, { t: "textarea" })}
  </div>`;
}

/* ------------------------------------------------------------------ vérification */
function rendreVerification() {
  const r = S.rapport;
  const ic = { ok: "✓", alerte: "!", erreur: "✕" };
  const ctrls = r ? r.controles.map((c) => `<div class="ctrl"><span class="ic ${c.statut}">${ic[c.statut]}</span><div style="flex:1">
      <strong>${esc(c.titre)}</strong>${c.resume ? ` <span class="muted">— ${esc(c.resume)}</span>` : ""}
      ${c.erreurs.length || c.alertes.length || c.infos.length ? `<ul>${c.erreurs.map((x) => `<li class="e">${esc(x)}</li>`).join("")}${c.alertes.map((x) => `<li class="a">${esc(x)}</li>`).join("")}${c.infos.map((x) => `<li class="i">${esc(x)}</li>`).join("")}</ul>` : ""}
    </div></div>`).join("") : '<p class="muted">Lancez la vérification pour contrôler la base en cours d\'édition.</p>';
  const cas = r?.cas ? `<p class="section-title" style="margin-top:20px">Cas de référence</p><table class="trace"><thead><tr><th>Cas</th><th>Attendu</th><th>Obtenu</th><th></th></tr></thead><tbody>
      ${r.cas.lignes.map((l) => `<tr><td>${esc(l.titre)}</td><td>${esc(l.attendu)} (${esc(l.cf_attendu)})</td><td>${esc(l.obtenu)} (${esc(l.cf_obtenu)})</td><td class="${l.ok ? "ok-txt" : "ko-txt"}">${l.ok ? "✓ conforme" : "✕ différent"}</td></tr>`).join("")}</tbody></table>` : "";
  const essai = S.essai ? `<div class="alert info" style="margin-top:10px">${S.essai}</div>` : "";
  return `<div class="card card-pad">
      <div class="ed-bar"><p class="section-title" style="margin:0">Vérification automatique ${r ? `· ${r.nb_erreurs} erreur(s), ${r.nb_alertes} alerte(s)` : ""}</p><span class="spacer"></span>
        <button class="btn primary small" data-act="verifier">Lancer la vérification</button></div>
      ${ctrls}${cas}
    </div>
    <div class="card card-pad" style="margin-top:16px">
      <p class="section-title">Essayer un cas avec la base en cours d'édition</p>
      <div class="ed-bar" style="margin:0"><select class="input" id="essai-cas" style="max-width:520px">${S.cas.map((c) => opt(c.id, c.titre)).join("")}</select>
        <button class="btn small" data-act="essayer">Essayer</button></div>
      ${essai}
    </div>`;
}

async function verifier() {
  try {
    $("#panel").style.opacity = ".6";
    S.rapport = await api("/api/expert/verifier", { base: S.draft });
    S.tab = "verification";
  } catch (e) {
    toast(e.message);
  } finally {
    $("#panel").style.opacity = "";
  }
  rendre();
}

async function essayer() {
  const c = S.cas.find((x) => x.id === $("#essai-cas").value);
  try {
    const r = await api("/api/expert/essayer", { base: S.draft, reponses: c.reponses });
    if (r.etat !== "resultat") S.essai = `Le moteur attend encore une réponse : « ${esc(r.question.texte)} »`;
    else {
      const h = r.resultat.hypothese;
      S.essai = `<strong>${esc(h.libelle)}</strong> — CF ${esc(h.cf_texte)} (${esc(h.lecture)})<br>Recommandations : ${r.resultat.recommandations.map((x) => esc(x.texte)).join(" ; ") || "aucune"}`;
    }
  } catch (e) {
    S.essai = `<span class="ko-txt">${esc(e.message)}</span>`;
  }
  rendre();
  $("#essai-cas").value = c.id;
}

/* ------------------------------------------------------------------ versions */
function rendreVersions() {
  const active = S.base.meta?.version;
  const items = S.versions.map((v) => `<div class="ver-item ${v.numero === active ? "current" : ""}">
      <span class="n">v${v.numero}</span>
      <span class="muted">${esc(new Date(v.date).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }))}</span>
      <span><strong>${esc(v.auteur)}</strong> — ${esc(v.motif)}</span>
      <span style="display:flex;gap:6px">${v.numero !== active ? `<button class="btn small" data-act="diff" data-n="${v.numero}">Différences</button>
        <button class="btn small" data-act="restaurer" data-n="${v.numero}">Restaurer</button>` : ""}</span>
    </div>${S.diffs[v.numero] ? `<div class="diff">${esc(S.diffs[v.numero].length ? S.diffs[v.numero].join("\n") : "Aucune différence avec la version active.")}</div>` : ""}`).join("");
  return `<div class="card card-pad"><p class="section-title">Historique (version, date, auteur, motif)</p>
    <p class="muted" style="font-size:13.5px;margin:0 0 6px">« Différences » compare une ancienne version à la version active. Restaurer crée une nouvelle version : rien n'est jamais effacé.</p>
    ${items || '<div class="empty">Aucune version.</div>'}</div>`;
}

/* ------------------------------------------------------------------ actions */
async function action(b) {
  const a = b.dataset.act;
  const d = S.draft;
  const i = +b.dataset.i;
  if (a === "filtre") S.niveau = b.dataset.v;
  else if (a === "add-regle") {
    const n = Math.max(0, ...d.regles.map((r) => parseInt(String(r.id).replace(/\D/g, "")) || 0)) + 1;
    const niveau = S.niveau === "1" ? 1 : 2;
    d.regles.push({ id: `R${n}`, niveau, actif: true, premisse: "", conclusion: niveau === 1 ? d.faits_intermediaires[0]?.id : d.diagnostics[0]?.id, cf: 0.5, recommandation: niveau === 2 ? "" : undefined, commentaire: "" });
    const h1 = d.heuristiques.find((h) => h.id === "H1");
    if (niveau === 2 && h1) h1.parametres.ordre.push(`R${n}`);
    toast(`Règle R${n} ajoutée en bas de la liste.`);
  } else if (a === "del-regle") {
    if (!confirm(`Supprimer la règle ${d.regles[i].id} ?`)) return;
    const id = d.regles[i].id;
    d.regles.splice(i, 1);
    const h1 = d.heuristiques.find((h) => h.id === "H1");
    if (h1) h1.parametres.ordre = h1.parametres.ordre.filter((x) => x !== id);
  } else if (a === "add-question") {
    d.questions.push({ id: `question_${d.questions.length + 1}`, etape: "clinique", phase: "recueil", type: "oui_non", certitude: true, texte: "", libelle: "" });
  } else if (a === "del-question") {
    if (!confirm(`Supprimer la question ${d.questions[i].id} ?`)) return;
    d.questions.splice(i, 1);
  } else if (a === "add-inter") d.faits_intermediaires.push({ id: `fait_${d.faits_intermediaires.length + 1}`, libelle: "", groupe: "clinique" });
  else if (a === "del-inter") d.faits_intermediaires.splice(i, 1);
  else if (a === "add-diag") d.diagnostics.push({ id: `diagnostic_${d.diagnostics.length + 1}`, libelle: "", gravite: "orange" });
  else if (a === "del-diag") d.diagnostics.splice(i, 1);
  else if (a === "add-cond" || a === "del-cond") {
    const arr = b.dataset.path.split(".").reduce((o, k) => o[/^\d+$/.test(k) ? +k : k], d);
    if (a === "add-cond") arr.push({ fait: d.faits_intermediaires[0]?.id, seuil: 0.4 });
    else arr.splice(i, 1);
  } else if (a.startsWith("fz-")) {
    const v = d.variables_floues[i], j = +b.dataset.j;
    if (a === "fz-add-ens") {
      const [lo, hi] = domaine(v);
      const n = v.ensembles.length + 1;
      v.ensembles.push({ id: `ensemble_${n}`, libelle: `ensemble ${n}`, forme: "croissante",
        points: [[Math.round(lo + (hi - lo) / 3), 0], [Math.round(lo + (2 * (hi - lo)) / 3), 1]] });
    } else if (a === "fz-del-ens") {
      if (!confirm(`Supprimer l'ensemble « ${v.ensembles[j].libelle || v.ensembles[j].id} » ? Les règles qui l'utilisent seront signalées par la vérification.`)) return;
      v.ensembles.splice(j, 1);
    } else if (a === "fz-add-pt") {
      const e = v.ensembles[j], pts = ptsEns(e), [x, m] = pts.at(-1);
      e.points = [...pts, [x + 10, m]];
      e.forme = "points";
    } else if (a === "fz-del-pt") v.ensembles[j].points.splice(+b.dataset.k, 1);
  } else if (a === "verifier") return verifier();
  else if (a === "essayer") return essayer();
  else if (a === "diff") {
    const v = await api(`/api/expert/version?n=${b.dataset.n}`);
    S.diffs[b.dataset.n] = v.differences;
  } else if (a === "restaurer") {
    if (!confirm(`Restaurer la version ${b.dataset.n} ? Elle deviendra une nouvelle version active${S.dirty ? " et vos modifications non enregistrées seront perdues" : ""}.`)) return;
    try {
      const r = await api("/api/expert/restaurer", { numero: +b.dataset.n });
      toast(`Version ${b.dataset.n} restaurée (nouvelle version v${r.meta.numero}).`);
      S.diffs = {};
      return ouvrir();
    } catch (e) {
      return toast(e.message);
    }
  }
  marquer();
  rendre();
}

function apresRendu() {
  $$("#panel [data-act]").forEach((b) => b.addEventListener("click", () => action(b)));
  $$("#panel [data-premisse]").forEach((inp) => analyser(inp));
}

function lireValeur(el) {
  const t = el.dataset.t;
  if (t === "bool") return el.checked;
  if (t === "boolstr") return el.value === "true";
  if (t === "num") return el.value === "" ? undefined : isNaN(Number(el.value)) ? el.value : Number(el.value);
  if (t === "list") return el.value.split(",").map((x) => x.trim()).filter(Boolean);
  if (t === "options") return el.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const [id, ...rest] = l.split(":");
    return { id: id.trim(), libelle: (rest.join(":").trim() || id.trim()) };
  });
  if (t === "text") return el.value === "" && /\.(commentaire|aide|recommandation_si_biopsie|valeur_si_parent_non|oppose|unite)$/.test(el.dataset.p) ? undefined : el.value;
  return el.value;
}

function surSaisie(e) {
  const el = e.target;
  if (el.dataset?.fzTest !== undefined) {
    S.fzTest[el.dataset.fzTest] = el.value;
    return majFlou(+el.dataset.fzTest);
  }
  if (el.dataset?.fzForme !== undefined) {
    if (e.type !== "change") return;
    const [i, j] = el.dataset.fzForme.split(".").map(Number);
    changerForme(S.draft.variables_floues[i].ensembles[j], el.value);
    marquer();
    return rendre();
  }
  if (!el.dataset || !el.dataset.p) return;
  if (el.dataset.t === "conditions") {
    const q = el.dataset.p.split(".").reduce((o, k) => o[/^\d+$/.test(k) ? +k : k], S.draft);
    try {
      const c = el.value.trim() ? JSON.parse(el.value) : {};
      delete q.masquer_si;
      delete q.afficher_si;
      if (c.masquer_si) q.masquer_si = c.masquer_si;
      if (c.afficher_si) q.afficher_si = c.afficher_si;
      el.style.borderColor = "";
    } catch {
      el.style.borderColor = "var(--rouge)";
      return;
    }
  } else {
    setPath(S.draft, el.dataset.p, lireValeur(el));
  }
  marquer();
  if (el.dataset.premisse !== undefined) {
    clearTimeout(minuteurs[el.dataset.p]);
    minuteurs[el.dataset.p] = setTimeout(() => analyser(el), 300);
  }
  if (el.dataset.fz !== undefined) majFlou(+el.dataset.fz);
  if (e.type === "change" && el.dataset.rerender !== undefined) rendre();
}
$("#panel").addEventListener("input", surSaisie);
$("#panel").addEventListener("change", (e) => {
  if (e.target.dataset?.rerender !== undefined || e.target.tagName === "SELECT") surSaisie(e);
});

$("#btn-verify").addEventListener("click", verifier);
$("#btn-reset").addEventListener("click", () => {
  if (!confirm("Abandonner toutes les modifications non enregistrées ?")) return;
  S.draft = clone(S.base);
  S.rapport = null;
  marquer();
  rendre();
});
$("#btn-save").addEventListener("click", () => {
  $("#save-motif").value = "";
  $("#dlg-save").showModal();
});
$("#save-form").addEventListener("submit", async (e) => {
  if (e.submitter?.value !== "ok") return;
  e.preventDefault();
  const motif = $("#save-motif").value.trim();
  if (!motif) return toast("Indiquez le motif de la modification.");
  try {
    const r = await api("/api/expert/enregistrer", { base: S.draft, motif });
    $("#dlg-save").close();
    S.rapport = r.rapport;
    toast(`Version v${r.meta.numero} enregistrée et active.`);
    S.diffs = {};
    await ouvrir();
  } catch (err) {
    $("#dlg-save").close();
    if (err.donnees?.rapport) {
      S.rapport = err.donnees.rapport;
      S.tab = "verification";
      rendre();
    }
    toast(err.message);
  }
});
window.addEventListener("beforeunload", (e) => {
  if (S.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

/* ------------------------------------------------------------------ démarrage */
(async () => {
  S.jeton = store.get("se-jeton");
  S.auteur = store.get("se-auteur");
  if (S.jeton) {
    try {
      await ouvrir();
    } catch {
      deconnecter();
    }
  }
})();
