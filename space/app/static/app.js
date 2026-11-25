// Consola del Piloto HAI-SSDLC — front sin dependencias (desktop + PWA).
"use strict";
const PWA = matchMedia("(display-mode: standalone)").matches || innerWidth < 760;
const H = {"X-Consola-Dispositivo": PWA ? "pwa" : "desktop"};
let YO = null;
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const chip = (e) => `<span class="chip e-${esc(e)}">${esc((e || "").replace(/_/g, " "))}</span>`;
const json = (o) => `<pre>${esc(JSON.stringify(o, null, 1))}</pre>`;

async function api(ruta, opc = {}) {
  const r = await fetch(ruta, {...opc, headers: {...H, ...(opc.headers || {})}});
  if (r.status === 401) { location.href = "/oauth/huggingface/login"; throw new Error("sin sesión"); }
  const t = r.headers.get("content-type") || "";
  const d = t.includes("json") ? await r.json() : await r.blob();
  if (!r.ok) throw new Error(d.detail || r.statusText);
  return d;
}
const post = (ruta, cuerpo) => api(ruta, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(cuerpo || {})});
function aviso(msg) { const a = $("#aviso"); a.textContent = msg; a.hidden = !msg; if (msg) setTimeout(() => (a.hidden = true), 8000); }
const puede = (a) => YO && YO.permisos.includes(a);

const VISTAS = [
  ["tablero", "D1 Tablero", "consultar"], ["gates", "D4 Gates", "consultar"], ["ejecucion", "Ejecución", "consultar"],
  ["alta", "D2 Alta", "alta", true], ["despliegues", "D5 Despliegues y defectos", "registrar", true],
  ["indicadores", "D6 Indicadores", "consultar"], ["auditoria", "D7 Auditoría", "auditoria"],
];

function nav() {
  const actual = (location.hash.slice(1) || "tablero").split("/")[0];
  $("#nav").innerHTML = VISTAS.filter(([, , p, d]) => puede(p) && !(d && PWA))
    .map(([id, t]) => `<a href="#${id}" class="${actual === id ? "activo" : ""}">${esc(t)}</a>`).join("");
}

async function ruta() {
  nav();
  const [v, ...arg] = (location.hash.slice(1) || "tablero").split("/");
  const f = {tablero, req, gates, ejecucion, alta, despliegues, indicadores, auditoria}[v] || tablero;
  try { await f(...arg); } catch (e) { $("#vista").innerHTML = `<p class="aviso">${esc(e.message)}</p>`; }
}

// ---------------------------------------------------------------- D1
async function tablero() {
  const filas = await api("/api/tablero");
  const etapas = ["Discovery", "Arquitectura", "Ingeniería", "Calidad", "DevOps", "Despliegue"];
  const abiertos = filas.reduce((n, f) => n + f.gates_abiertos.length, 0);
  const desplegados = filas.filter((f) => f.estado === "desplegado").length;
  $("#vista").innerHTML = `<h2>Tablero · ${esc(YO.pilot)}</h2>
  <div class="tarjetas"><div class="tarjeta"><span class="tenue">Requerimientos</span><b>${filas.length}</b></div>
  <div class="tarjeta"><span class="tenue">Gates abiertos</span><b>${abiertos}</b></div>
  <div class="tarjeta"><span class="tenue">Desplegados</span><b>${desplegados}</b></div>
  <div class="tarjeta"><span class="tenue">Próximos cierres (Lima)</span><b style="font-size:16px">${esc(YO.cierre_ventanas.join(" · "))}</b></div>
  ${puede("reanudar") ? `<div class="tarjeta"><button class="b" id="reanudar">Reanudar ahora</button></div>` : ""}</div>
  <table><thead><tr><th>REQ</th><th>Estado</th>${etapas.map((e) => `<th class="${e === "Despliegue" ? "" : "solo-desktop"}">${e}</th>`).join("")}<th>Gates</th></tr></thead>
  <tbody>${filas.map((f) => `<tr class="clic" data-req="${esc(f.req)}"><td><b>${esc(f.req)}</b><br><small class="tenue">${esc(f.entrada_pipeline || "")}</small></td>
  <td>${esc(f.estado)}</td>${etapas.map((e) => `<td class="${e === "Despliegue" ? "" : "solo-desktop"}">${chip(f.etapas[e])}</td>`).join("")}
  <td>${f.gates_abiertos.map(esc).join("<br>")}</td></tr>`).join("") || `<tr><td colspan="9" class="tenue">Sin requerimientos todavía.</td></tr>`}</tbody></table>`;
  document.querySelectorAll("tr[data-req]").forEach((tr) => (tr.onclick = () => (location.hash = `req/${tr.dataset.req}`)));
  const b = $("#reanudar"); if (b) b.onclick = () => reanudar();
}

async function reanudar(reqs) {
  if (!confirm(`¿Lanzar el job del pipeline para ${reqs ? reqs.join(", ") : "todos los requerimientos"}? (GPU, se cobra por uso)`)) return;
  const r = await post("/api/reanudar", {reqs: reqs || []});
  aviso(`Job lanzado: ${r.job_id}`); location.hash = `ejecucion/${r.job_id}`;
}

// ---------------------------------------------------------------- D3
async function req(id, art) {
  const d = await api(`/api/req/${encodeURIComponent(id)}/dag`);
  $("#vista").innerHTML = `<h2>${esc(id)} <small class="tenue">${esc(d.estado?.estado || "registrado")}</small></h2>
  ${puede("reanudar") ? `<p><button class="b sec" id="re1">Reanudar este requerimiento</button></p>` : ""}
  <div class="dag">${d.etapas.map((e) => `<div class="etapa"><b>${esc(e.etapa)}</b>${e.nodos.map((n) => `<div class="nodo" data-art="${esc(n.artefacto)}">
   ${chip(n.estado)} <b>${esc(n.id)}</b><small>${esc(n.agente || "")}</small><small>${esc(n.modelo || "")}</small>
   <small>rondas governance: ${n.rondas_governance} · entradas: ${n.entradas}</small></div>`).join("")}</div>`).join("")}</div>
  <div id="panel"></div>`;
  document.querySelectorAll(".nodo").forEach((n) => (n.onclick = () => (location.hash = `req/${id}/${n.dataset.art}`)));
  const b = $("#re1"); if (b) b.onclick = () => reanudar([id]);
  if (art) await panel(id, art);
}

async function panel(id, art) {
  const p = await api(`/api/req/${encodeURIComponent(id)}/paso/${encodeURIComponent(art)}`);
  const tabs = {
    "Input": () => p.input.length ? p.input.map((x, i) => `<h3>Ronda ${x?.ronda ?? i}</h3>${json(x)}`).join("") : "<p class='tenue'>Sin registro de input (G2).</p>",
    "Output": () => json(p.output) + Object.entries(p.derivados).map(([n, t]) => `<h3>${esc(n)}</h3><pre>${esc(t)}</pre>`).join(""),
    "Rondas de governance": () => p.rondas_governance.length ? p.rondas_governance.map((r) => `<h3>Ronda ${r.round} · ${esc(r.ts)}</h3>
       ${r.hallazgos.map((h) => `<div class="hallazgo sev-${esc(h.severidad)}">[${esc(h.severidad)}] ${esc(h.regla)}: ${esc(h.detalle)}</div>`).join("")}
       <details><summary>Salida rechazada</summary>${json(r.output)}</details>`).join("") : "<p class='tenue'>Aprobado por governance en la ronda 0.</p>",
    "Decisión y dictamen": () => json(p.decision),
    "Devoluciones": () => p.devoluciones.length ? json(p.devoluciones) : "<p class='tenue'>Sin devoluciones.</p>",
    "Eventos": () => p.eventos.length ? json(p.eventos) : "<p class='tenue'>Sin eventos en la telemetría publicada.</p>",
  };
  const dibuja = (t) => {
    $("#panel").innerHTML = `<h3>${esc(art)} · ${esc(p.agente || "")}</h3><div class="pestanas">${Object.keys(tabs).map((k) =>
      `<button class="${k === t ? "activo" : ""}" data-t="${esc(k)}">${esc(k)}</button>`).join("")}</div>${tabs[t]()}`;
    document.querySelectorAll(".pestanas button").forEach((b) => (b.onclick = () => dibuja(b.dataset.t)));
  };
  dibuja("Output");
}

// ---------------------------------------------------------------- D4
const CHECK = {product_owner: "PO", tech_lead: "TL", solution_architect: "SA", security_architect: "SEC", data_architect: "DA",
  api_architect: "API", qa_lead: "QA", devops_engineer: "DevOps", release_manager: "RM"};
async function gates() {
  const gs = await api("/api/gates");
  $("#vista").innerHTML = `<h2>Gates pendientes (${gs.length})</h2>
  ${gs.length ? "" : "<p class='tenue'>No hay gates abiertos.</p>"}
  ${gs.map((g, i) => `<div class="gate ${g.discrepancia ? "disc" : ""}" data-i="${i}">
    <div class="fila"><b>${esc(g.req)} / ${esc(g.artefacto)}</b> ${g.escalado ? chip("escalado") : chip("esperando_gate")}
    <span class="tenue">rol ${esc(CHECK[g.rol] || g.rol)} · solicitado ${esc(g.solicitado)}</span></div>
    ${g.discrepancia ? `<p class="sev-mayor">⚠ Governance y el dictamen IA no coinciden: revisa con cuidado.</p>` : ""}
    <h3>Hallazgos de governance</h3>${g.hallazgos_governance.map((h) => `<div class="hallazgo sev-${esc(h.severidad)}">[${esc(h.severidad)}] ${esc(h.regla)}: ${esc(h.detalle)}</div>`).join("") || "<span class='tenue'>ninguno</span>"}
    <h3>Dictamen IA <small class="tenue">(${esc(g.dictamen_ia?.por || "—")}; apoyo, no decide)</small></h3>
    ${g.dictamen_ia ? `<p>Recomienda <b>${esc(g.dictamen_ia.recomendacion)}</b>. ${esc(g.dictamen_ia.motivo || g.dictamen_ia.resumen || "")}</p>
      ${g.dictamen_ia.checklist ? json(g.dictamen_ia.checklist) : ""}` : "<p class='tenue'>Sin dictamen.</p>"}
    <details><summary>Artefacto (JSON)</summary>${json(g.contenido)}</details>
    ${puede("decidir") ? `<label>Motivo (obligatorio para devolver)</label><textarea class="motivo"></textarea>
    <div class="fila" style="margin-top:8px"><button class="b" data-d="approved">Aprobar</button><button class="b peligro" data-d="returned">Devolver</button></div>` : ""}
  </div>`).join("")}`;
  document.querySelectorAll(".gate button[data-d]").forEach((b) => (b.onclick = async () => {
    const box = b.closest(".gate"), g = gs[+box.dataset.i], motivo = box.querySelector(".motivo").value.trim();
    if (b.dataset.d === "returned" && !motivo) return aviso("Devolver exige motivo.");
    if (!confirm(`${b.dataset.d === "approved" ? "Aprobar" : "Devolver"} ${g.req}/${g.artefacto}?`)) return;
    const r = await post("/api/gates/decidir", {decisiones: [{req: g.req, artefacto: g.artefacto, decision: b.dataset.d, motivo}],
      instruccion: `${b.dataset.d === "approved" ? "Apruebo" : "Devuelvo"} ${g.req}/${g.artefacto}${motivo ? ": " + motivo : ""}`});
    aviso(`Registrado (${r.ts}).`); gates();
  }));
}

// ---------------------------------------------------------------- ejecución
async function ejecucion(jobId) {
  const [js, prog] = await Promise.all([api("/api/jobs"), api("/api/programacion").catch(() => [])]);
  const activos = prog.some((p) => !p.suspendido);
  $("#vista").innerHTML = `<h2>Ejecución</h2>
  <div class="tarjetas"><div class="tarjeta"><span class="tenue">Reanudación automática</span><b style="font-size:16px">${prog.length ? (activos ? "activa" : "suspendida") : "no programada"}</b>
  <small class="tenue">${prog.map((p) => esc(p.schedule) + " UTC").join(" · ")}</small></div>
  ${puede("reanudar") ? `<div class="tarjeta fila">${prog.length ? `<button class="b sec" id="sw">${activos ? "Suspender" : "Activar"}</button>` : `<button class="b sec" id="prog">Programar cierres ${esc(YO.cierre_ventanas.join(" y "))}</button>`}
  <button class="b" id="ya">Reanudar ahora</button></div>` : ""}</div>
  <table><thead><tr><th>Job</th><th>Estado</th><th>Creado</th><th></th></tr></thead><tbody>
  ${js.map((j) => `<tr><td><a href="#ejecucion/${esc(j.job_id)}">${esc(j.job_id)}</a></td><td>${esc(j.estado)}</td><td>${esc(j.creado)}</td>
  <td>${puede("reanudar") && ["RUNNING", "SCHEDULING"].includes(j.estado) ? `<button class="b peligro" data-c="${esc(j.job_id)}">Cancelar</button>` : ""}</td></tr>`).join("") || "<tr><td colspan=4 class='tenue'>Sin jobs de la consola.</td></tr>"}
  </tbody></table><div id="log"></div>`;
  const on = (id, f) => { const b = $(id); if (b) b.onclick = f; };
  on("#ya", () => reanudar());
  on("#prog", async () => { await post("/api/programacion", {}); ejecucion(jobId); });
  on("#sw", async () => { await post("/api/programacion", {activo: !activos}); ejecucion(jobId); });
  document.querySelectorAll("button[data-c]").forEach((b) => (b.onclick = async () => {
    if (confirm(`¿Cancelar ${b.dataset.c}?`)) { await post(`/api/jobs/${b.dataset.c}/cancelar`); ejecucion(); }
  }));
  if (jobId) await log(jobId);
}

async function log(jobId) {
  const agente = $("#filtro")?.value || "";
  const [st, l] = await Promise.all([api(`/api/jobs/${jobId}`), api(`/api/jobs/${jobId}/logs${agente ? "?agente=" + encodeURIComponent(agente) : ""}`)]);
  $("#log").innerHTML = `<h3>Log en vivo · ${esc(jobId)} · ${esc(st.estado)}</h3>
  <div class="fila"><input id="filtro" placeholder="Filtrar por agente (p. ej. solution-architect-agent)" value="${esc(agente)}" style="max-width:420px"><button class="b sec" id="ref">Actualizar</button></div>
  <h3>Eventos (${l.eventos.length})</h3><pre>${esc(l.eventos.slice(-60).map((e) => `${e.ts || ""} ${e.event} ${e.req_id || ""} ${e.agent || ""} ${e.artefact || ""} ${e.decision || ""}`).join("\n"))}</pre>
  <h3>Salida</h3><pre>${esc(l.lineas.join("\n"))}</pre>`;
  $("#ref").onclick = () => log(jobId);
  if (["RUNNING", "SCHEDULING"].includes(st.estado) && location.hash.includes(jobId)) setTimeout(() => location.hash.includes(jobId) && log(jobId), 15000);
}

// ---------------------------------------------------------------- D2
const CAMPOS = [["req_id", "REQ-ID"], ["titulo", "Título"], ["proyecto", "Proyecto"], ["solicitante", "Solicitante"], ["tipo", "Tipo", ["Funcional", "No funcional", "Técnico", "Regulatorio"]],
  ["origen", "Origen"], ["campana", "Campaña"], ["fecha_registro", "Fecha de registro (AAAA-MM-DD)"], ["fecha_release_comprometida", "Release comprometido (opcional)"],
  ["puntos_historia", "Puntos de historia"], ["reglas_negocio", "Reglas de negocio (BR-001, BR-010…)"], ["datos_personales", "Datos personales", ["no", "si"]]];
const TEXTOS = [["necesidad", "Necesidad de negocio"], ["resultado_esperado", "Resultado esperado"], ["restricciones", "Restricciones conocidas (una por línea)"],
  ["preguntas_abiertas", "Preguntas abiertas (una por línea)"], ["historia_original", "Historia original"], ["criterios_aceptacion", "Criterios de aceptación"], ["notas_refinamiento", "Notas de refinamiento"]];
async function alta() {
  $("#vista").innerHTML = `<h2>Alta de requerimiento (BusinessRequest v1.1)</h2>
  <form id="f"><div class="rejilla">${CAMPOS.map(([n, t, op]) => `<div><label>${esc(t)}</label>${op ? `<select name="${n}">${op.map((o) => `<option>${o}</option>`).join("")}</select>` : `<input name="${n}">`}</div>`).join("")}</div>
  ${TEXTOS.map(([n, t]) => `<label>${esc(t)}</label><textarea name="${n}"></textarea>`).join("")}
  <h3>…o sube el ZIP de la carpeta <code>input/</code></h3><input type="file" name="zip" accept=".zip">
  <div class="fila" style="margin-top:12px"><button class="b sec" data-m="validar">Validar y ver vista previa</button><button class="b" data-m="confirmar" disabled id="conf">Confirmar alta</button></div></form>
  <div id="prev"></div>`;
  const f = $("#f");
  f.querySelectorAll("button[data-m]").forEach((b) => (b.onclick = async (ev) => {
    ev.preventDefault();
    const fd = new FormData(); fd.append("modo", b.dataset.m);
    const z = f.zip.files[0];
    if (z) fd.append("zip", z); else fd.append("formulario", JSON.stringify(Object.fromEntries([...new FormData(f)].filter(([k]) => k !== "zip"))));
    try {
      const r = await api("/api/alta", {method: "POST", body: fd});
      $("#prev").innerHTML = `<h3>${r.registrado ? "Registrado" : "Vista previa"} · SHA-256 <code>${esc(r.sha256)}</code></h3>${json(r.business_request)}`;
      $("#conf").disabled = !!r.registrado; if (r.registrado) aviso(`Alta de ${r.business_request.req_id} registrada.`);
    } catch (e) { $("#conf").disabled = true; $("#prev").innerHTML = `<p class="aviso">${esc(e.message)}</p>`; }
  }));
}

// ---------------------------------------------------------------- D5
async function despliegues() {
  const r = await api("/api/registros");
  $("#vista").innerHTML = `<h2>Despliegues y defectos</h2><div class="rejilla">
  <form id="fd"><h3>Defecto escapado</h3><label>REQ-ID</label><input name="req" required>
   <label>Etapa de detección</label><select name="etapa_deteccion"><option>smoke</option><option>staging</option><option>aceptacion</option></select>
   <label>Severidad</label><select name="severidad"><option>critica</option><option>alta</option><option>media</option><option>baja</option></select>
   <label>Agente de origen (si se sabe)</label><input name="etapa_origen"><label>Descripción</label><textarea name="descripcion" required></textarea>
   <p><button class="b">Registrar defecto</button></p></form>
  <form id="fp"><h3>Resultado post-despliegue</h3><label>REQ-ID</label><input name="req" required>
   <label>Resultado</label><select name="resultado"><option>rollback</option><option>correccion</option></select>
   <label>Motivo</label><textarea name="motivo" required></textarea><p><button class="b">Registrar</button></p></form></div>
  ${Object.entries(r).map(([k, v]) => `<h3>${esc(k)} (${v.length})</h3>${json(v)}`).join("")}`;
  const envia = (id, ruta) => ($(id).onsubmit = async (ev) => {
    ev.preventDefault(); const o = Object.fromEntries(new FormData(ev.target));
    if (!confirm(`¿Registrar para ${o.req}? Queda con la hora real de Lima y no se edita.`)) return;
    await post(ruta, o); aviso("Registrado."); despliegues();
  });
  envia("#fd", "/api/defecto"); envia("#fp", "/api/despliegue");
}

// ---------------------------------------------------------------- D6
async function indicadores() {
  const r = await api("/api/indicadores");
  const h = r.hipotesis?.resumen;
  $("#vista").innerHTML = `<h2>Indicadores</h2><p class="tenue">${r.eventos} eventos de telemetría y registros.</p>
  ${h ? `<table><tbody>${Object.entries(h).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("")}</tbody></table>` : "<p class='tenue'>Aún no hay telemetría del piloto.</p>"}
  <h3>Por agente</h3>${json(r.agentes)}`;
}

// ---------------------------------------------------------------- D7
async function auditoria() {
  const a = await api("/api/auditoria");
  const m = a.global.matriz || {};
  const fila = (k) => `<tr><th>${k === "humano_aprueba" ? "Humano aprueba" : "Humano devuelve"}</th><td>${m[k]?.ia_aprueba ?? 0}</td><td>${m[k]?.ia_devuelve ?? 0}</td></tr>`;
  $("#vista").innerHTML = `<h2>Auditoría <small class="tenue">(solo lectura)</small></h2>
  <div class="tarjetas"><div class="tarjeta"><span class="tenue">Decisiones con dictamen</span><b>${a.global.n}</b></div>
  <div class="tarjeta"><span class="tenue">Acuerdo</span><b>${a.global.acuerdo ?? "—"}</b></div><div class="tarjeta"><span class="tenue">κ de Cohen</span><b>${a.global.kappa ?? "—"}</b></div>
  ${puede("exportar") ? `<div class="tarjeta"><a class="b" href="/api/evidencia.zip" style="text-decoration:none;color:#fff;display:inline-block;padding:7px 12px;background:var(--acento);border-radius:6px">Paquete de evidencia (ZIP)</a></div>` : ""}</div>
  <table style="max-width:420px"><thead><tr><th></th><th>IA aprueba</th><th>IA devuelve</th></tr></thead><tbody>${fila("humano_aprueba")}${fila("humano_devuelve")}</tbody></table>
  <h3>Por agente</h3><table><thead><tr><th>Agente</th><th>n</th><th>Acuerdo</th><th>κ</th></tr></thead><tbody>
  ${Object.entries(a.por_agente).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${v.acuerdo ?? "—"}</td><td>${v.kappa ?? "—"}</td></tr>`).join("")}</tbody></table>
  <h3>Por clase de modelo</h3><table><thead><tr><th>Clase</th><th>n</th><th>Acuerdo</th><th>κ</th></tr></thead><tbody>
  ${Object.entries(a.por_clase).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${v.acuerdo ?? "—"}</td><td>${v.kappa ?? "—"}</td></tr>`).join("")}</tbody></table>
  <div class="pestanas"><button class="activo" data-t="log">decision_log</button><button data-t="dev">Desviaciones</button><button data-t="acc">Registro de accesos</button></div><div id="t"></div>`;
  const t = {log: () => json(a.decision_log), dev: () => `<pre>${esc(a.desviaciones || "Sin desviaciones registradas.")}</pre>`, acc: () => json(a.accesos)};
  $("#t").innerHTML = t.log();
  document.querySelectorAll(".pestanas button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".pestanas button").forEach((x) => x.classList.toggle("activo", x === b)); $("#t").innerHTML = t[b.dataset.t]();
  }));
}

// ---------------------------------------------------------------- arranque
(async () => {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  try { YO = await api("/api/yo"); } catch (e) { $("#vista").innerHTML = `<p class="aviso">${esc(e.message)}</p><p><a href="/oauth/huggingface/login">Iniciar sesión con Hugging Face</a></p>`; return; }
  $("#usuario").innerHTML = `${esc(YO.nombre)} · ${esc(YO.roles.join(", "))} · <a href="/oauth/huggingface/logout">salir</a>`;
  addEventListener("hashchange", ruta); ruta();
})();
