const $ = (id) => document.getElementById(id);
const labels = {current: "Actual", historical: "Histórico", draft: "Borrador"};
let noticeTimer;
let firstStatusRead = true;
function node(tag, text, className) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; }
function toast(text, error = false) { clearTimeout(noticeTimer); $("toast").textContent = text; $("toast").className = "toast" + (error ? " error" : ""); noticeTimer = setTimeout(() => $("toast").classList.add("hidden"), 9000); }
async function api(path, options = {}) { const r = await fetch(path, options); const data = await r.json(); if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Revisa los campos del formulario."); return data; }
const json = (method, body) => ({method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
function reference(source) {
  let page = source.page ? (source.page_end && source.page_end !== source.page ? `Páginas ${source.page}–${source.page_end}` : `Página ${source.page}`) : "Página no verificada";
  if (!source.page && /\.(txt|md|csv|tsv|html?)$/i.test(source.filename || "")) page = source.location || "Ubicación de texto";
  if (source.page && source.page_origin === "generated_pdf") page += " del PDF local";
  return `${page} · Sección: ${source.section ? source.section.split(" > ").pop() : "sin identificar"}`;
}
function previewLink(source) {
  if (!source.preview_url || !/^\/api\/documents\/[0-9a-f]{32}\/preview$/.test(source.preview_url)) return null;
  const link = node("a", source.page ? `Abrir página ${source.page} ↗` : "Abrir PDF de referencia ↗", "preview-link");
  link.href = source.preview_url + (source.page ? "#page=" + source.page : ""); link.target = "_blank"; link.rel = "noreferrer";
  return link;
}
function showPage(page) { document.querySelectorAll(".page").forEach(e => e.classList.toggle("hidden", e.id !== page)); document.querySelectorAll(".nav-item").forEach(e => e.classList.toggle("active", e.dataset.page === page)); $("page-title").textContent = {consult: "Consultar", library: "Documentos", settings: "Conectar Gemini"}[page]; window.scrollTo(0, 0); }
document.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => showPage(b.dataset.page)));
async function refresh() {
  const s = await api("/api/status");
  if (firstStatusRead) {
    if (s.key_configured && s.free_confirmed && s.model_allowed) $("mode").value = "gemini";
    firstStatusRead = false;
  }
  $("doc-count").textContent = s.documents; $("nav-count").textContent = s.documents;
  $("call-count").textContent = `${s.calls_today} / ${s.daily_limit}`;
  $("connection").textContent = s.key_configured && s.free_confirmed ? "Gemini configurado · Free por confirmar en Google" : "Modo local · Gemini sin conectar";
  $("key-dot").classList.toggle("ready", s.key_configured && s.free_confirmed);
  $("model-name").textContent = `Modelo configurado: ${s.model}. Límite local: ${s.daily_limit} llamadas al día (UTC).`;
  $("empty-banner").classList.toggle("hidden", s.documents > 0); await library();
}
async function loadDemo(button) { button.disabled = true; try { const d = await api("/api/demo", {method: "POST"}); toast(d.message); await refresh(); } catch (e) { toast(e.message, true); } finally { button.disabled = false; } }
$("load-demo").addEventListener("click", e => loadDemo(e.currentTarget)); $("library-demo").addEventListener("click", e => loadDemo(e.currentTarget));
document.querySelectorAll("[data-question]").forEach(b => b.addEventListener("click", () => { $("question").value = b.dataset.question; $("question").focus(); }));
$("question-form").addEventListener("submit", async e => { e.preventDefault(); const button = $("ask-button"); button.disabled = true; button.textContent = "Consultando…"; try { const data = await api("/api/ask", json("POST", {question: $("question").value.trim(), block: $("block").value, status: $("filter-status").value, mode: $("mode").value})); renderAnswer(data); await refresh(); } catch (error) { toast(error.message, true); } finally { button.disabled = false; button.textContent = "Consultar ↗"; } });
function renderAnswer(data) { $("results").classList.remove("hidden"); $("claims").replaceChildren(); $("sources").replaceChildren(); $("result-title").textContent = {matches: "Coincidencias en tus documentos", answered: "Respuesta con fuentes", partial: "Encontré contexto; falta el dato específico", insufficient: data.stage === "generation" ? "Los fragmentos no bastan para responder" : "Sin coincidencias en la búsqueda", filtered: "Los filtros excluyen documentos coincidentes", cloud_permission_required: "Hay información local sin permiso para Gemini", empty_library: "Añade un documento para empezar", conflict: "Fuentes en conflicto", unverified: "Respuesta sin verificar"}[data.status] || "Resultados"; $("result-message").textContent = data.message; $("result-meta").textContent = `${data.api_called ? data.model : data.cached ? data.model + " · caché local" : "Sin llamada a la API"} · ${data.elapsed_ms} ms`; $("sources-count").textContent = `${data.sources.length} fragmentos`;
  data.claims.forEach((c, index) => {
    const source = data.sources.find(s => s.source_id === c.source_id);
    const card = node("div", undefined, "claim" + (index === 0 ? " direct-answer" : ""));
    card.append(node("p", c.text));
    const ref = node("button", `[${c.source_id}] ${source ? reference(source) : "Ver fuente"}`, "citation-link");
    ref.addEventListener("click", () => { const detail = $("source-" + c.source_id); detail.open = true; detail.scrollIntoView({behavior: "smooth", block: "center"}); });
    card.append(ref);
    const evidence = node("details", undefined, "claim-evidence");
    evidence.append(node("summary", source && source.kind === "table" ? "Ver encabezados y celdas de la tabla" : "Ver cita literal"), node("blockquote", c.quote));
    card.append(evidence);
    if (source) { const link = previewLink(source); if (link) card.append(link); }
    $("claims").append(card);
  });
  data.sources.forEach((s, i) => {
    const d = node("details", undefined, "source"); d.id = "source-" + s.source_id; d.open = !data.claims.length && i === 0;
    const summary = node("summary", `[${s.source_id}] ${s.title}`);
    summary.append(node("small", `${reference(s)} · ${s.location} · Versión ${s.version}`));
    d.append(summary, node("div", `${s.filename} · ${s.block === "general" ? "General" : "Categoría: " + s.block} · ${labels[s.status]}`, "source-badges"), node("div", s.text, "source-body"));
    const link = previewLink(s); if (link) d.append(link);
    $("sources").append(d);
  });
  $("results").scrollIntoView({behavior: "smooth", block: "start"});
}
function refreshCategories(categories) {
  const filter = $("block"), selected = filter.value;
  const values = [...new Set(["general", ...categories])].sort((a, b) => a.localeCompare(b, "es"));
  // Keep the active filter even when its last document was removed.
  if (selected && selected !== "all" && !values.includes(selected)) values.push(selected);
  filter.replaceChildren();
  const all = node("option", "Todas las categorías"); all.value = "all"; filter.append(all);
  $("category-options").replaceChildren();
  values.forEach(value => {
    const option = node("option", value === "general" ? "General · compartida" : value); option.value = value; filter.append(option);
    const suggestion = node("option"); suggestion.value = value; $("category-options").append(suggestion);
  });
  filter.value = selected || "all";
}
async function library() { const data = await api("/api/documents"); refreshCategories(data.categories || data.documents.map(doc => doc.block)); $("documents-list").replaceChildren(); if (!data.documents.length) $("documents-list").append(node("p", "Tu biblioteca está vacía. Añade un documento o carga el ejemplo ficticio.", "muted")); $("version-warning").classList.toggle("hidden", data.version_warnings.length === 0); $("version-warning").textContent = data.version_warnings.map(w => `Hay ${w.documents.length} versiones marcadas como actuales de «${w.family}» (${w.block}). Revisa su estado.`).join(" ");
  data.documents.forEach(doc => { const card = node("article", undefined, "doc-card"); const top = node("div", undefined, "doc-top"); const desc = node("div"); desc.append(node("h3", doc.title), node("p", `${doc.filename} · ${doc.block === "general" ? "General" : "Categoría: " + doc.block} · v${doc.version} · ${doc.chunk_count} fragmentos`), node("p", `Familia: ${doc.family} · ${doc.document_date || "Sin fecha"}`)); top.append(desc); card.append(top); const controls = node("div", undefined, "doc-controls"); const select = node("select"); select.setAttribute("aria-label", "Estado de " + doc.title); Object.entries(labels).forEach(([value, text]) => { const option = node("option", text); option.value = value; select.append(option); }); select.value = doc.status;
    const privacy = node("label", undefined, "checkbox"); const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.checked = doc.allow_cloud; privacy.append(checkbox, node("span", "Permitir fragmentos en Gemini")); const update = async () => { try { await api("/api/documents/" + doc.id, json("PATCH", {status: select.value, allow_cloud: checkbox.checked})); await refresh(); } catch (e) { toast(e.message, true); await refresh(); } }; select.addEventListener("change", update); checkbox.addEventListener("change", () => { if (checkbox.checked && !confirm("¿Autorizas enviar fragmentos de este documento a Google? El nivel gratuito puede usar su contenido para mejorar productos.")) { checkbox.checked = false; return; } update(); });
    const remove = node("button", "Eliminar", "delete-button"); remove.addEventListener("click", async () => { if (!confirm(`¿Eliminar «${doc.title}» y sus fragmentos de la biblioteca local?`)) return; try { await api("/api/documents/" + doc.id, {method: "DELETE"}); $("results").classList.add("hidden"); await refresh(); toast("Documento eliminado de la biblioteca."); } catch (e) { toast(e.message, true); } }); controls.append(select, privacy, remove); card.append(controls); doc.warnings.forEach(w => card.append(node("p", w, "hint"))); $("documents-list").append(card); });
}
$("file").addEventListener("change", () => { if (!$("upload-title").value && $("file").files[0]) $("upload-title").value = $("file").files[0].name.replace(/\.[^.]+$/, "").slice(0, 180); });
$("upload-form").addEventListener("submit", async e => { e.preventDefault(); const button = $("upload-button"); button.disabled = true; try { const f = $("file").files[0]; if (f.size > 10 * 1024 * 1024) throw new Error("Máximo 10 MB por archivo."); const data = await api("/api/documents", {method: "POST", body: new FormData(e.currentTarget)}); toast(data.created ? `Documento guardado: ${data.chunks} fragmentos. ${data.warnings.join(" ")}` : "Este archivo y versión ya estaban en la biblioteca."); e.target.reset(); await refresh(); } catch (error) { toast(error.message, true); } finally { button.disabled = false; } });
$("settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const b = $("save-key"), feedback = $("settings-feedback");
  b.disabled = true; b.textContent = "Guardando…";
  feedback.classList.remove("hidden"); feedback.textContent = "Guardando la clave en tu PC…";
  try {
    const data = await api("/api/settings", json("POST", {api_key: $("api-key").value, free_confirmed: $("free-confirmed").checked}));
    $("api-key").value = "";
    feedback.textContent = data.message + " Ya puedes elegir Respuesta con Gemini al consultar.";
    toast(data.message); $("mode").value = "gemini"; await refresh();
  } catch (error) {
    feedback.textContent = error.message;
    toast(error.message, true);
  } finally {
    b.disabled = false; b.textContent = "Guardar clave en mi PC ↗";
  }
});
refresh().catch(e => toast("No se pudo conectar con la aplicación local: " + e.message, true));
