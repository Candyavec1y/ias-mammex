/* MAMMEX — interface médecin */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fr = (x, n = 2) => (x === null || x === undefined ? "—" : Number(x).toFixed(n).replace(".", ","));

const etat = {
  info: null,
  reponses: {},
  historique: [],
  question: null,
  etapes: [],
  resultat: null,
  ouiEnAttente: false,
  pourquoiOuvert: false,
  comment: false,
};

/* ------------------------------------------------------------------ outils */
async function api(url, data) {
  const opts = data === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
  let r;
  try {
    r = await fetch(url, opts);
  } catch (e) {
    throw new Error("Le serveur MAMMEX ne répond pas. Vérifiez que la fenêtre de lancement est toujours ouverte.");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.erreur || `Erreur ${r.status}`);
  return j;
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function montrer(vue) {
  for (const id of ["home-view", "consult-view", "result-view", "report-view"]) {
    $("#" + id).classList.toggle("hidden", id !== vue);
  }
  window.scrollTo(0, 0);
}

function question(id) {
  return (etat.info?.questions || []).find((q) => q.id === id);
}

function texteReponse(qid, r) {
  const q = question(qid);
  if (!q || !r) return "";
  const v = r.valeur;
  if (q.type === "nombre") return `${v} ${q.unite || ""}`.trim();
  if (q.type === "choix") {
    if (v === "jnsp") return "Je ne sais pas";
    const o = (q.options || []).find((o) => o.id === v);
    return o ? o.libelle : v;
  }
  if (v === "oui") return r.certitude ? `Oui (${r.certitude})` : "Oui";
  if (v === "non") return "Non";
  return "Je ne sais pas";
}

/* ------------------------------------------------------------------ déroulement */
async function avancer() {
  try {
    const r = await api("/api/consultation", { reponses: etat.reponses });
    if (r.etat === "question") {
      etat.question = r.question;
      etat.etapes = r.etapes;
      etat.ouiEnAttente = false;
      etat.pourquoiOuvert = !!r.question.redemandee;
      rendreQuestion();
      montrer("consult-view");
    } else {
      etat.resultat = r.resultat;
      etat.comment = false;
      rendreResultat();
      montrer("result-view");
    }
  } catch (e) {
    toast(e.message);
  }
}

function repondre(valeur, certitude) {
  const q = etat.question;
  const avant = etat.reponses[q.id];
  const rep = { valeur };
  if (certitude) rep.certitude = certitude;
  if (q.redemandee && avant) rep.fois = (avant.fois || 1) + 1;
  etat.historique.push({ id: q.id, avant });
  etat.reponses[q.id] = rep;
  avancer();
}

function precedent() {
  const h = etat.historique.pop();
  if (!h) {
    montrer("home-view");
    return;
  }
  if (h.avant) etat.reponses[h.id] = h.avant;
  else delete etat.reponses[h.id];
  avancer();
}

function nouvelleConsultation() {
  etat.reponses = {};
  etat.historique = [];
  etat.resultat = null;
  avancer();
}

/* ------------------------------------------------------------------ écran question */
function rendreStepper() {
  const q = etat.question;
  $("#stepper").innerHTML = etat.etapes
    .map((e, i) => {
      const cls = i < q.etape_index ? "done" : i === q.etape_index ? "current" : "";
      const opt = e.id === "biopsie" && i !== q.etape_index ? ' <span class="opt">si utile</span>' : "";
      return `<div class="step ${cls}"><span class="num">${i < q.etape_index ? "✓" : i + 1}</span>${esc(e.libelle)}${opt}</div>`;
    })
    .join("");
}

function svgFlou(f, x) {
  const ens = f.ensembles[0];
  const W = 150, H = 44, x0 = 20, x1 = 80;
  const px = (a) => ((Math.min(Math.max(a, x0), x1) - x0) / (x1 - x0)) * W;
  const y = (m) => H - 6 - m * (H - 14);
  const a = px(ens.debut), b = px(ens.fin);
  let mu = x == null || isNaN(x) ? null : x <= ens.debut ? 0 : x >= ens.fin ? 1 : (x - ens.debut) / (ens.fin - ens.debut);
  const marker = mu === null ? "" : `<circle cx="${px(x)}" cy="${y(mu)}" r="4" fill="var(--accent)"/>`;
  return `<svg width="${W}" height="${H}" viewBox="-2 0 ${W + 4} ${H}" aria-hidden="true">
    <line x1="0" y1="${H - 6}" x2="${W}" y2="${H - 6}" stroke="var(--line-strong)"/>
    <polyline points="0,${y(0)} ${a},${y(0)} ${b},${y(1)} ${W},${y(1)}" fill="none" stroke="var(--text)" stroke-width="1.6"/>
    <text x="${a}" y="${H}" font-size="9" fill="var(--faint)" text-anchor="middle">${ens.debut}</text>
    <text x="${b}" y="${H}" font-size="9" fill="var(--faint)" text-anchor="middle">${ens.fin}</text>
    ${marker}</svg>`;
}

function texteFlou(f, x) {
  const ens = f.ensembles[0];
  if (x === "" || x == null || isNaN(x)) return `Saisissez l'âge : il sera converti en degré d'appartenance à « ${esc(ens.libelle)} ».`;
  const mu = x <= ens.debut ? 0 : x >= ens.fin ? 1 : (x - ens.debut) / (ens.fin - ens.debut);
  return `<b>${esc(ens.libelle)} à ${Math.round(mu * 100)} %</b> (μ = ${fr(mu)})`;
}

function rendreQuestion() {
  const q = etat.question;
  rendreStepper();
  const deja = q.deja || {};
  let corps = "";
  if (q.type === "oui_non") {
    const sel = (v) => (deja.valeur === v && !etat.ouiEnAttente ? " selected" : "");
    corps = `<div class="answers">
      <button class="answer${etat.ouiEnAttente ? " selected" : sel("oui")}" data-v="oui">Oui <span class="kbd">O</span></button>
      <button class="answer${sel("non")}" data-v="non">Non <span class="kbd">N</span></button>
      <button class="answer${sel("jnsp")}" data-v="jnsp">Je ne sais pas <span class="kbd">J</span></button>
    </div>`;
    if (etat.ouiEnAttente) {
      corps += `<div class="certitude-box"><div class="label">Quelle est votre certitude ?</div><div class="answers">
        <button class="answer${deja.certitude === "certain" ? " selected" : ""}" data-c="certain">Certain <span class="kbd">1</span></button>
        <button class="answer${deja.certitude === "probable" ? " selected" : ""}" data-c="probable">Probable <span class="kbd">2</span></button>
        <button class="answer${deja.certitude === "possible" ? " selected" : ""}" data-c="possible">Possible <span class="kbd">3</span></button>
      </div></div>`;
    }
  } else if (q.type === "nombre") {
    const v = deja.valeur ?? "";
    corps = `<div class="num-row">
        <input class="num-input" id="num" type="number" inputmode="numeric" min="${q.min ?? ""}" max="${q.max ?? ""}" value="${esc(v)}" aria-label="${esc(q.texte)}">
        <span class="muted">${esc(q.unite || "")}</span>
        <button class="btn primary" id="num-ok">Valider <span class="kbd" style="color:#fff;border-color:rgba(255,255,255,.4)">Entrée</span></button>
      </div>
      ${q.floue ? `<div class="fuzzy"><span id="fz-svg">${svgFlou(q.floue, v === "" ? null : Number(v))}</span><span id="fz-txt">${texteFlou(q.floue, v === "" ? null : Number(v))}</span></div>` : ""}`;
  } else if (q.type === "choix") {
    corps = `<div class="answers">${(q.options || [])
      .map((o) => `<button class="answer wide${deja.valeur === o.id ? " selected" : ""}" data-v="${esc(o.id)}">${esc(o.libelle)}</button>`)
      .join("")}
      <button class="answer wide${deja.valeur === "jnsp" ? " selected" : ""}" data-v="jnsp">Je ne sais pas</button></div>`;
  }

  $("#qcard").innerHTML = `
    <div class="qmeta">
      <span class="chip">Étape ${q.etape_index + 1} · ${esc(q.etape_libelle)}</span>
      ${q.redemandee ? '<span class="chip warn">Redemandée (MR3) : donnée nécessaire pour conclure</span>' : ""}
    </div>
    <h2 class="qtext">${esc(q.texte)}</h2>
    ${q.aide ? `<p class="qhelp">${esc(q.aide)}</p>` : ""}
    ${corps}
    ${etat.pourquoiOuvert ? `<div class="why">${esc(q.pourquoi)}</div>` : ""}
    <div class="qfoot">
      <button class="btn ghost" id="btn-prev">← Précédent</button>
      <span class="spacer"></span>
      <button class="btn small" id="btn-why" aria-expanded="${etat.pourquoiOuvert}">Pourquoi ?</button>
    </div>`;

  $("#qcard").querySelectorAll("[data-v]").forEach((b) =>
    b.addEventListener("click", () => {
      const v = b.dataset.v;
      if (q.type === "oui_non" && v === "oui" && q.certitude) {
        etat.ouiEnAttente = true;
        rendreQuestion();
        $("#qcard [data-c]")?.focus();
      } else {
        repondre(v);
      }
    })
  );
  $("#qcard").querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => repondre("oui", b.dataset.c)));
  $("#btn-prev").addEventListener("click", precedent);
  $("#btn-why").addEventListener("click", () => {
    etat.pourquoiOuvert = !etat.pourquoiOuvert;
    rendreQuestion();
  });
  const num = $("#num");
  if (num) {
    const valider = () => {
      const x = Number(num.value);
      if (num.value === "" || isNaN(x)) return toast("Saisissez un nombre.");
      if ((q.min != null && x < q.min) || (q.max != null && x > q.max)) return toast(`Valeur attendue entre ${q.min} et ${q.max}.`);
      repondre(x);
    };
    num.addEventListener("input", () => {
      if (!q.floue) return;
      const x = num.value === "" ? null : Number(num.value);
      $("#fz-svg").innerHTML = svgFlou(q.floue, x);
      $("#fz-txt").innerHTML = texteFlou(q.floue, x);
    });
    num.addEventListener("keydown", (e) => e.key === "Enter" && valider());
    $("#num-ok").addEventListener("click", valider);
    setTimeout(() => num.focus(), 30);
  }
  rendreDossier();
}

function rendreDossier() {
  const groupes = {};
  for (const id of Object.keys(etat.reponses)) {
    const q = question(id);
    if (!q) continue;
    (groupes[q.etape] ||= []).push(`<div class="kv"><span>${esc(q.libelle || q.texte)}</span><span>${esc(texteReponse(id, etat.reponses[id]))}</span></div>`);
  }
  const html = (etat.info?.etapes || [])
    .filter((e) => groupes[e.id])
    .map((e) => `<div class="dossier-groupe"><div class="g">${esc(e.libelle)}</div>${groupes[e.id].join("")}</div>`)
    .join("");
  $("#dossier").innerHTML = `<h3>Dossier en cours</h3>${html || '<div class="empty">Aucune réponse pour l\'instant.</div>'}`;
}

document.addEventListener("keydown", (e) => {
  if ($("#consult-view").classList.contains("hidden") || !etat.question) return;
  if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey || e.altKey) return;
  const q = etat.question;
  const k = e.key.toLowerCase();
  if (q.type === "oui_non") {
    if (etat.ouiEnAttente && ["1", "2", "3"].includes(k)) return repondre("oui", ["certain", "probable", "possible"][+k - 1]);
    if (k === "o") {
      if (q.certitude) {
        etat.ouiEnAttente = true;
        return rendreQuestion();
      }
      return repondre("oui");
    }
    if (k === "n") return repondre("non");
    if (k === "j") return repondre("jnsp");
  }
  if (e.key === "ArrowLeft") precedent();
});

/* ------------------------------------------------------------------ résultat */
const LIB_STATUT = {
  declenchee: "déclenchée",
  desactivee: "désactivée",
  bloquee: "bloquée",
  echec: "échec",
  non_declenchee: "non déclenchée",
  non_testee: "non testée",
  non_testable: "non testée",
};

function blocVerdict(res) {
  const h = res.hypothese;
  const pct = h.cf == null ? 0 : Math.max(0, Math.min(1, h.cf)) * 100;
  const ticks = [0.2, 0.4, 0.7, 0.9].map((t) => `<span style="left:${t * 100}%">${fr(t, 1)}</span>`).join("");
  return `
    <div class="result-top">
      <div class="verdict g-${esc(h.gravite)}" role="status">
        <span class="lbl">Hypothèse principale</span>
        <span class="hyp">${esc(h.libelle)}</span>
        <span class="tag"><span class="dot"></span>${esc(res.gravite_libelle)}${h.regle ? ` · règle ${esc(h.regle)}` : ""}</span>
      </div>
      <div class="card gauge-card">
        <span class="section-title" style="margin:0">Facteur de certitude</span>
        <span class="gauge-val">${h.cf == null ? "—" : esc(h.cf_texte)}</span>
        <span class="gauge-read">${esc(h.lecture)}</span>
        <div class="gauge" role="meter" aria-valuemin="0" aria-valuemax="1" aria-valuenow="${h.cf ?? 0}"><div class="gauge-fill" style="width:${pct}%"></div></div>
        <div class="gauge-ticks">${ticks}</div>
      </div>
    </div>`;
}

function rendreResultat() {
  const res = etat.resultat;
  const recos = res.recommandations.map((r) => `<li><span>${esc(r.texte)}<span class="src">${esc(r.source)}</span></span></li>`).join("");
  const alertes = res.alertes.map((a) => `<div class="alert ${esc(a.niveau)}">${esc(a.texte)}</div>`).join("");
  const manq = res.donnees_manquantes.length
    ? `<div class="missing">${res.donnees_manquantes.map((m) => `<span class="${m.bloquante ? "bloq" : ""}" title="${m.bloquante ? "bloque une règle" : ""}">${esc(m.libelle)}</span>`).join("")}</div>`
    : '<div class="empty">Aucune.</div>';
  const sec = res.secondaires.length
    ? res.secondaires.map((s) => `<div class="sec-row"><span>${esc(s.libelle)} <span class="muted mono">${esc(s.regle)}</span></span><span class="v">${esc(s.cf_texte)} · ${esc(s.lecture)}</span></div>`).join("")
    : '<div class="empty">Aucune.</div>';
  const faits = res.faits_intermediaires
    .map((f) => `<div class="card fact"><div class="n">${esc(f.libelle)}</div><div class="v">${f.complet || f.cf != null ? esc(f.cf_texte) : "?"}</div><div class="r">${f.complet || f.cf != null ? esc(f.lecture) : "non établi"}</div></div>`)
    .join("");

  $("#result-view").innerHTML = `
    ${blocVerdict(res)}
    <div class="result-grid">
      <div class="card card-pad">
        <p class="section-title">Recommandations</p>
        <ol class="reco">${recos || '<li><span class="muted">Aucune.</span></li>'}</ol>
      </div>
      <div class="card card-pad">
        ${alertes ? `<p class="section-title">Alertes</p>${alertes}` : ""}
        <p class="section-title" style="margin-top:${alertes ? "14px" : "0"}">Données manquantes</p>
        ${manq}
        <p class="section-title" style="margin-top:14px">Hypothèses secondaires</p>
        ${sec}
      </div>
    </div>
    <div class="facts">${faits}</div>
    <div class="actions no-print">
      <button class="btn primary" id="btn-comment" aria-expanded="${etat.comment}">Comment ?</button>
      <button class="btn" id="btn-report">Rapport imprimable</button>
      <button class="btn" id="btn-edit">← Modifier la dernière réponse</button>
      <span style="flex:1"></span>
      <button class="btn" id="btn-new">Nouvelle consultation</button>
    </div>
    <div id="explain" class="card card-pad explain ${etat.comment ? "" : "hidden"}">${rendreExplication(res)}</div>`;

  $("#btn-comment").addEventListener("click", () => {
    etat.comment = !etat.comment;
    $("#explain").classList.toggle("hidden", !etat.comment);
    $("#btn-comment").setAttribute("aria-expanded", etat.comment);
    if (etat.comment) $("#explain").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("#btn-report").addEventListener("click", () => {
    rendreRapport();
    montrer("report-view");
  });
  $("#btn-edit").addEventListener("click", precedent);
  $("#btn-new").addEventListener("click", nouvelleConsultation);
}

function rendreExplication(res) {
  const lignes = res.comment
    .map((c) => `<div class="comment-line ${c.niveau === 2 ? "n2" : ""}"><div>${esc(c.texte)}</div>${c.calcul ? `<div class="calc">${esc(c.calcul)}</div>` : ""}</div>`)
    .join("");
  const retenue = res.hypothese.regle;
  const n2 = res.trace_niveau2
    .map((t) => {
      const st = t.regle === retenue ? "retenue" : t.statut;
      const lib = t.regle === retenue ? "retenue" : t.statut === "declenchee" ? "secondaire" : LIB_STATUT[t.statut] || t.statut;
      return `<tr><td class="mono">${esc(t.regle)}</td><td>${esc(t.conclusion_libelle)}<div class="muted" style="font-size:12.5px">SI ${esc(t.premisse)}</div></td>
        <td class="mono">${esc(t.calcul_complet || t.calcul || "")}${t.combinaison ? `<br>${esc(t.combinaison)}` : ""}</td>
        <td><span class="st st-${st}">${esc(lib)}</span>${t.raison ? `<div class="muted" style="font-size:12.5px;margin-top:3px">${esc(t.raison)}</div>` : ""}</td></tr>`;
    })
    .join("");
  const n1 = res.trace_niveau1
    .map((e) => `<tr><td class="mono">${esc(e.cycle)}</td><td class="mono">${esc(e.regle)}</td><td>${esc(e.conclusion_libelle)}<div class="muted" style="font-size:12.5px">SI ${esc(e.premisse)}</div></td>
      <td class="mono">${esc(e.calcul)}${e.combinaison ? `<br>combinaison : ${esc(e.combinaison)}` : ""}</td></tr>`)
    .join("");
  const rej = res.rejets_niveau1
    .map((e) => `<tr><td class="mono">—</td><td class="mono">${esc(e.regle)}</td><td>${esc(e.conclusion_libelle)}<div class="muted" style="font-size:12.5px">SI ${esc(e.premisse)}</div></td><td class="muted">${esc(e.raison)}</td></tr>`)
    .join("");
  const meta = res.meta_regles.map((m) => `<div class="meta-line"><b>${esc(m.id)}</b>${esc(m.texte)}</div>`).join("");
  const heur = res.heuristiques.map((m) => `<div class="meta-line"><b>${esc(m.id)}</b>${esc(m.texte)}</div>`).join("");
  return `
    <h3>Comment le système a conclu</h3>
    ${lignes}
    <h3>Méta-règles et heuristiques appliquées</h3>
    ${meta}${heur}
    <details class="calc-details"><summary>Détail des calculs de CF</summary>
      <h3>Niveau 2 · chaînage arrière (ordre de test : ${esc(res.ordre_niveau2.join(" → "))})</h3>
      <table class="trace"><thead><tr><th>Règle</th><th>Hypothèse</th><th>Calcul</th><th>Statut</th></tr></thead><tbody>${n2}</tbody></table>
      <h3>Niveau 1 · chaînage avant (cycles jusqu'à saturation)</h3>
      <table class="trace"><thead><tr><th>Cycle</th><th>Règle</th><th>Fait conclu</th><th>Calcul</th></tr></thead><tbody>${n1}${rej}</tbody></table>
    </details>`;
}

/* ------------------------------------------------------------------ rapport */
function rendreRapport() {
  const res = etat.resultat;
  const h = res.hypothese;
  const date = new Date().toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });
  const parEtape = {};
  for (const d of res.donnees) (parEtape[d.etape_libelle] ||= []).push(d);
  const donnees = Object.entries(parEtape)
    .map(([e, ds]) => `<tr><td colspan="2" style="color:var(--text);font-weight:650;padding-top:10px">${esc(e)}</td></tr>` + ds.map((d) => `<tr><td>${esc(d.libelle)}</td><td>${esc(d.valeur)}</td></tr>`).join(""))
    .join("");
  const faits = res.faits_intermediaires.map((f) => `<tr><td>${esc(f.libelle)}</td><td>${f.complet || f.cf != null ? `${esc(f.cf_texte)} (${esc(f.lecture)})` : "non établi"}</td></tr>`).join("");
  $("#report-view").innerHTML = `
    <div class="report-bar no-print">
      <button class="btn" id="rp-back">← Retour au résultat</button>
      <button class="btn primary" id="rp-print">Imprimer / enregistrer en PDF</button>
    </div>
    <div class="card report">
      <div class="report-head">
        <div><h1>MAMMEX · Synthèse de consultation</h1><div class="muted" style="font-size:13px">${esc(date)} · base de connaissances v${esc(etat.info?.version ?? "?")}</div></div>
        <div class="report-fields">
          <label for="rp-ref">Réf. dossier</label><input id="rp-ref" placeholder="à compléter">
          <label for="rp-med">Médecin</label><input id="rp-med" placeholder="à compléter">
        </div>
      </div>
      <h2>Conclusion</h2>
      <div class="concl g-${esc(h.gravite)}">${esc(h.libelle)} — ${h.cf == null ? esc(h.lecture) : `CF ${esc(h.cf_texte)} (${esc(h.lecture)})`}</div>
      <h2>Recommandations</h2>
      <ol style="margin:0;padding-left:20px">${res.recommandations.map((r) => `<li>${esc(r.texte)}</li>`).join("")}</ol>
      ${res.alertes.length ? `<h2>Alertes</h2><ul style="margin:0;padding-left:20px">${res.alertes.map((a) => `<li>${esc(a.texte)}</li>`).join("")}</ul>` : ""}
      <h2>Données manquantes</h2>
      <p style="margin:0">${res.donnees_manquantes.length ? res.donnees_manquantes.map((m) => esc(m.libelle)).join(", ") : "Aucune."}</p>
      <h2>Données saisies</h2>
      <table>${donnees}</table>
      <h2>Faits établis (niveau 1)</h2>
      <table>${faits}</table>
      <h2>Justification</h2>
      ${res.comment.map((c) => `<div style="font-size:14px;margin-bottom:4px">${esc(c.texte)}${c.calcul ? ` <span class="mono muted">[${esc(c.calcul)}]</span>` : ""}</div>`).join("")}
      <div class="foot">Document produit par un système expert d'aide à la décision. Il ne remplace pas l'avis du médecin ;
        seule l'histologie confirme un cancer. Facteurs de certitude pédagogiques, non validés cliniquement.</div>
    </div>`;
  $("#rp-back").addEventListener("click", () => montrer("result-view"));
  $("#rp-print").addEventListener("click", () => window.print());
}

/* ------------------------------------------------------------------ démarrage */
async function init() {
  try {
    etat.info = await api("/api/info");
    $("#version-pill").textContent = `Base v${etat.info.version ?? "?"}`;
    const cas = await api("/api/cas");
    const sel = $("#demo-select");
    // un groupe par cas (« Cas 4 », « Cas 4 (variante) »… sont réunis)
    const groupes = new Map();
    cas.forEach((c, i) => {
      const g = (c.titre.match(/^Cas \d+/) || ["Autres"])[0];
      if (!groupes.has(g)) groupes.set(g, []);
      groupes.get(g).push(`<option value="${i}">${esc(c.titre.replace(/^Cas \d+\s*/, "").replace(/^—\s*/, "") || c.titre)}</option>`);
    });
    sel.insertAdjacentHTML("beforeend", [...groupes].map(([g, opts]) => `<optgroup label="${esc(g)}">${opts.join("")}</optgroup>`).join(""));
    sel.disabled = false;
    sel.addEventListener("change", () => {
      if (sel.value === "") return;
      const c = cas[+sel.value];
      sel.value = "";
      etat.reponses = JSON.parse(JSON.stringify(c.reponses));
      etat.historique = Object.keys(c.reponses).map((id) => ({ id, avant: undefined }));
      avancer();
    });
  } catch (e) {
    toast(e.message);
  }
}
$("#btn-start").addEventListener("click", nouvelleConsultation);
init();
