"use strict";

/* Lumen: tiny dependency-free frontend for the search API.
   All text from the API is inserted with textContent, never as HTML. */

const EXAMPLES = [
  "a man slowly loses his grip on reality",
  "friends reunite for one last road trip",
  "a thief plans a perfect heist",
  "a lonely robot learns to love",
];

const MOODS = [
  { key: "happy", label: "Happy" },
  { key: "dark", label: "Dark" },
  { key: "romantic", label: "Romantic" },
  { key: "fast_paced", label: "Fast-paced" },
];

// How big the web of similar movies is: k = direct neighbours,
// k_outer = new neighbours added around each of those.
const WEB_SIZES = {
  small: { k: 6, k_outer: 2 },
  medium: { k: 8, k_outer: 3 },
  large: { k: 12, k_outer: 4 },
};

const $ = (selector, root = document) => root.querySelector(selector);

// How strongly well-known films are favoured in the result order (0 = pure best match).
let popularity = 0.35;
let titleWeight = null;      // null = decided automatically from the query
let hideObscure = false;
let hasVotes = false;        // set from /api/health: does the dataset carry ratings and vote counts?
let lastSearch = null;       // remembered so changing a setting can re-run it

// What "Hide obscure films" means. With ratings in the data we use them; without,
// we keep only the best-known 40 % of the dataset.
const OBSCURE_WITH_VOTES = { min_votes: 150, min_rating: 5.5 };
const OBSCURE_BY_POPULARITY = { min_popularity: 0.6 };

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children.filter((c) => c !== null && c !== undefined));
  return node;
}

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  node.append(...children);
  return node;
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const movieCache = new Map(); // id -> movie (plus _why: matched themes for text searches)

async function api(path, body) {
  const options = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (!response.ok) {
    let detail = "Something went wrong.";
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch { /* keep the generic message */ }
    throw new Error(detail);
  }
  return response.json();
}

/* ---------- posters ---------- */

function poster(movie) {
  const fallback = () => el("div", { class: "poster", role: "img", "aria-label": `No poster for ${movie.title}` }, movie.title);
  if (!movie.poster_url) return fallback();
  const img = el("img", {
    class: "poster",
    src: movie.poster_url,
    alt: `Poster for ${movie.title}`,
    loading: "lazy",
    referrerpolicy: "no-referrer",
  });
  img.addEventListener("error", () => img.replaceWith(fallback()));
  return img;
}

/* ---------- results ---------- */

const statusEl = $("#status");
const resultsEl = $("#results");
const headingEl = $("#results-heading");
const headEl = $("#results-head");

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function renderResults(movies, heading, explainThemes, note = "") {
  resultsEl.replaceChildren();
  movies.forEach((m) => movieCache.set(m.id, { ...m, _why: explainThemes ? m.explanation.matched_themes : [] }));

  headEl.hidden = false;
  headingEl.textContent = heading;
  setStatus(movies.length ? note : "No matches. Try describing the plot in different words, or switch off Hide obscure films.");

  for (const m of movies) {
    const pct = m.explanation.similarity_pct;
    const exact = Boolean(m.explanation.matched_title);
    resultsEl.append(el(
      "button",
      { class: "card", type: "button", onclick: () => openMovie(m.id) },
      poster(m),
      el("h3", {}, m.title),
      el("span", { class: "year" }, m.year ? String(m.year) : "Year unknown"),
      el("div", { class: "sim", role: "img", "aria-label": exact ? "Title match" : `Similarity ${pct}%` },
        el("span", { style: `width:${exact ? 100 : Math.max(4, Math.min(100, pct))}%` })),
      el("span", { class: exact ? "sim-label exact" : "sim-label" }, exact ? "Title match" : `${pct}% similar`),
    ));
  }
}

async function runSearch(path, body, heading, button, explainThemes, rerun = false) {
  lastSearch = { path, body, heading, button, explainThemes };
  button.disabled = true;
  setStatus("Searching…");
  try {
    const isText = path === "/api/search";
    const data = await api(path, {
      ...body,
      popularity,
      ...(isText ? { title_weight: titleWeight } : {}),
      ...(hideObscure ? (hasVotes ? OBSCURE_WITH_VOTES : OBSCURE_BY_POPULARITY) : {}),
    });
    let note = "";
    if (isText && data.anchor) note = `Showing "${data.anchor.title}" first, then films similar to it.`;
    else if (isText && titleWeight === null && data.weights && data.weights.title >= 0.4) note = "This looks like a title, so title matches count more. Change it under Fine-tune.";
    renderResults(data.results, heading, explainThemes, note);
    if (!rerun) headEl.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" });
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    button.disabled = false;
  }
}

/* ---------- search forms ---------- */

const describeForm = $("#panel-describe");
const queryInput = $("#query");

describeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) {
    setStatus("Describe the movie first, even in a few words.", true);
    queryInput.focus();
    return;
  }
  runSearch("/api/search", { query, k: 24 }, "Movies that match your description", $("button[type=submit]", describeForm), true);
});

// Enter submits, Shift+Enter adds a new line.
queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    describeForm.requestSubmit();
  }
});

for (const text of EXAMPLES) {
  $("#examples").append(el("button", {
    type: "button",
    onclick: () => { queryInput.value = text; describeForm.requestSubmit(); },
  }, text));
}

const moodForm = $("#panel-mood");
const sliderValues = {};

for (const mood of MOODS) {
  const output = el("output", { for: `mood-${mood.key}` }, "0");
  const input = el("input", { type: "range", id: `mood-${mood.key}`, min: "0", max: "100", value: "0" });
  input.addEventListener("input", () => { output.textContent = input.value; });
  sliderValues[mood.key] = input;
  $("#sliders").append(el("div", { class: "slider" }, el("label", { for: input.id }, mood.label, output), input));
}

moodForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const body = { base_query: $("#mood-text").value.trim(), k: 24 };
  for (const mood of MOODS) body[mood.key] = Number(sliderValues[mood.key].value) / 100;
  runSearch("/api/mood-search", body, "Movies that fit this mood", $("button[type=submit]", moodForm), false);
});

/* ---------- result settings: order, hide obscure films, fine-tune ---------- */

function rerun() {
  if (!lastSearch) return;
  const { path, body, heading, button, explainThemes } = lastSearch;
  runSearch(path, body, heading, button, explainThemes, true);
}

let rerunTimer = null;
const rerunSoon = () => { clearTimeout(rerunTimer); rerunTimer = setTimeout(rerun, 300); };

const sortButtons = document.querySelectorAll("#sort-by button");
const popularitySlider = $("#ft-popularity");
const popularityOut = $("#ft-popularity-out");

function setPopularity(value) {
  popularity = value;
  popularitySlider.value = String(Math.round(value * 100));
  popularityOut.textContent = popularitySlider.value;
  // The three preset buttons light up only when the value matches one of them.
  sortButtons.forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.popularity) === value)));
}

sortButtons.forEach((button) => button.addEventListener("click", () => {
  setPopularity(Number(button.dataset.popularity));
  rerun();
}));

popularitySlider.addEventListener("input", () => {
  setPopularity(Number(popularitySlider.value) / 100);
  rerunSoon();
});

const titleSlider = $("#ft-title");
const titleAuto = $("#ft-title-auto");
const titleOut = $("#ft-title-out");

function updateTitleControls() {
  titleSlider.disabled = titleAuto.checked;
  titleWeight = titleAuto.checked ? null : Number(titleSlider.value) / 100;
  titleOut.textContent = titleAuto.checked ? "Auto" : titleSlider.value;
}
titleAuto.addEventListener("change", () => { updateTitleControls(); rerun(); });
titleSlider.addEventListener("input", () => { updateTitleControls(); rerunSoon(); });

const hideButton = $("#hide-obscure");
hideButton.addEventListener("click", () => {
  hideObscure = !hideObscure;
  hideButton.setAttribute("aria-pressed", String(hideObscure));
  rerun();
});

const fineButton = $("#finetune-toggle");
const finePanel = $("#finetune");
fineButton.addEventListener("click", () => {
  finePanel.hidden = !finePanel.hidden;
  fineButton.setAttribute("aria-expanded", String(!finePanel.hidden));
});

// Ask the server whether the dataset has ratings, so "Hide obscure films" can use them.
api("/api/health").then((h) => { hasVotes = Boolean(h.has_votes); }).catch(() => { /* keep the default */ });

/* ---------- tabs ---------- */

const tabs = [$("#tab-describe"), $("#tab-mood")];
const panels = [describeForm, moodForm];

function selectTab(index) {
  tabs.forEach((tab, i) => {
    tab.setAttribute("aria-selected", String(i === index));
    tab.tabIndex = i === index ? 0 : -1;
    panels[i].hidden = i !== index;
  });
  setStatus("");
}

tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => selectTab(i));
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const next = (i + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    selectTab(next);
    tabs[next].focus();
  });
});

/* ---------- detail dialog ---------- */

const dialog = $("#detail");
let currentId = null;
let webSize = "medium";

$("#detail-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }); // backdrop click
dialog.addEventListener("close", hideTip);

for (const button of document.querySelectorAll("#web-size button")) {
  button.addEventListener("click", async () => {
    webSize = button.dataset.size;
    document.querySelectorAll("#web-size button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    if (currentId !== null) await loadGraph(currentId);
  });
}

async function fetchGraph(id) {
  const { k, k_outer } = WEB_SIZES[webSize];
  return api(`/api/graph/${id}?depth=2&k=${k}&k_outer=${k_outer}`);
}

async function loadGraph(id) {
  try {
    drawGraph(id, await fetchGraph(id));
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function openMovie(id) {
  try {
    let movie = movieCache.get(id);
    if (!movie) {
      movie = { ...(await api(`/api/movie/${id}`)), _why: [] };
      movieCache.set(id, movie);
    }
    const graph = await fetchGraph(id);
    currentId = id;
    showMovie(movie);
    drawGraph(id, graph);
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
  } catch (err) {
    setStatus(err.message, true);
  }
}

function showMovie(movie) {
  $("#detail-title").textContent = movie.title;
  $("#detail-meta").textContent = [movie.year, (movie.genres || []).join(", ")].filter(Boolean).join(", ");
  $("#detail-overview").textContent = movie.overview;

  const why = $("#detail-why");
  why.hidden = !(movie._why && movie._why.length);
  why.textContent = why.hidden ? "" : `Matches your search on: ${movie._why.join(", ")}`;

  const credits = [];
  if (movie.director) credits.push(`Directed by ${movie.director}.`);
  if (movie.actors && movie.actors.length) credits.push(`Starring ${movie.actors.join(", ")}.`);
  $("#detail-credits").textContent = credits.join(" ");

  $("#detail-poster").replaceChildren(poster(movie));
  $("#detail-themes").replaceChildren(...(movie.keywords || []).slice(0, 10).map((k) => el("span", { class: "chip" }, k)));
}

/* ---------- similarity web ---------- */

const GW = 900, GH = 600; // SVG coordinate space (matches the viewBox)
const svg = $("#graph");
const tip = $("#tip");

function shorten(text, max = 26) {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

/* A small force simulation: every dot pushes the others away, every link pulls
   its two dots together (stronger similarity = shorter link). The movie you
   opened stays in the middle. Runs once, synchronously, so the layout is the
   same every time. */
function layoutGraph(graph, centerId) {
  const nodes = graph.nodes.map((n) => ({ ...n, vx: 0, vy: 0 }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = graph.edges.filter((e) => byId.has(e.source) && byId.has(e.target));

  const weights = edges.map((e) => e.weight);
  const lo = Math.min(...weights), hi = Math.max(...weights);
  const strength = (w) => (hi === lo ? 0.5 : (w - lo) / (hi - lo));

  const cx = GW / 2, cy = GH / 2;
  const center = byId.get(centerId);
  center.x = cx; center.y = cy; center.fixed = true;

  // Start positions: ring 1 on an ellipse, ring 2 fanned out behind its closest ring-1 neighbour.
  const ring1 = nodes.filter((n) => n.ring === 1);
  ring1.forEach((n, i) => {
    n.angle = (2 * Math.PI * i) / ring1.length - Math.PI / 2;
    n.x = cx + 160 * Math.cos(n.angle);
    n.y = cy + 130 * Math.sin(n.angle);
  });

  const fan = new Map();
  for (const n of nodes.filter((m) => m.ring === 2)) {
    let parent = null, best = -1;
    for (const e of edges) {
      const otherId = e.source === n.id ? e.target : e.target === n.id ? e.source : null;
      const other = otherId === null ? null : byId.get(otherId);
      if (other && other.ring === 1 && e.weight > best) { best = e.weight; parent = other; }
    }
    parent = parent || ring1[0] || center;
    const index = fan.get(parent.id) || 0;
    fan.set(parent.id, index + 1);
    const angle = (parent.angle || 0) + (index - 1) * 0.3;
    n.x = cx + 285 * Math.cos(angle);
    n.y = cy + 235 * Math.sin(angle);
  }

  const STEPS = 320;
  for (let step = 0; step < STEPS; step++) {
    for (const n of nodes) { n.fx = 0; n.fy = 0; }

    for (let i = 0; i < nodes.length; i++) {          // repulsion
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 0.5;
        if (d2 > 200 * 200) continue;
        const d = Math.sqrt(d2), f = 2800 / d2;
        a.fx += (dx / d) * f; a.fy += (dy / d) * f;
        b.fx -= (dx / d) * f; b.fy -= (dy / d) * f;
      }
    }

    for (const e of edges) {                           // springs
      const a = byId.get(e.source), b = byId.get(e.target);
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const rest = 70 + (1 - strength(e.weight)) * 110;
      const f = (d - rest) * 0.03;
      a.fx += (dx / d) * f; a.fy += (dy / d) * f;
      b.fx -= (dx / d) * f; b.fy -= (dy / d) * f;
    }

    for (const n of nodes) {                           // gravity + move
      if (n.fixed) continue;
      n.fx += (cx - n.x) * 0.006;
      n.fy += (cy - n.y) * 0.006;
      n.vx = Math.max(-12, Math.min(12, (n.vx + n.fx) * 0.82));
      n.vy = Math.max(-12, Math.min(12, (n.vy + n.fy) * 0.82));
      n.x = Math.max(60, Math.min(GW - 60, n.x + n.vx));
      n.y = Math.max(34, Math.min(GH - 34, n.y + n.vy));
    }
  }

  // The simulation tends to bunch everything up. Stretch the result so the web
  // fills the canvas; the opened movie stays in the middle.
  const reachX = Math.max(...nodes.map((n) => Math.abs(n.x - cx)), 1);
  const reachY = Math.max(...nodes.map((n) => Math.abs(n.y - cy)), 1);
  const sx = Math.min(2.4, (GW / 2 - 90) / reachX);
  const sy = Math.min(2.4, (GH / 2 - 50) / reachY);
  for (const n of nodes) {
    n.x = cx + (n.x - cx) * sx;
    n.y = cy + (n.y - cy) * sy;
  }

  return { nodes, edges, byId, strength };
}

function showTip(node, weightToCenter) {
  const lines = [node.year ? String(node.year) : "", (node.genres || []).slice(0, 2).join(", ")].filter(Boolean).join(", ");
  tip.replaceChildren(
    el("b", {}, node.title),
    lines ? el("span", {}, lines) : null,
    weightToCenter ? el("span", {}, `${weightToCenter}% similar to this movie`) : null,
  );
  tip.hidden = false;

  const rect = svg.getBoundingClientRect();
  const scale = rect.width / GW;
  const half = 110;
  tip.style.left = `${Math.max(half, Math.min(rect.width - half, node.x * scale))}px`;
  tip.style.top = `${Math.max(48, node.y * scale - 14)}px`;
}

function hideTip() { tip.hidden = true; }

function drawGraph(centerId, graph) {
  svg.replaceChildren();
  svg.classList.remove("has-focus");
  hideTip();
  $("#similar").replaceChildren();
  $("#similar-outer").replaceChildren();

  const { nodes, edges, byId, strength } = layoutGraph(graph, centerId);

  const adjacent = new Map(nodes.map((n) => [n.id, new Set()]));
  const toCenter = new Map();
  for (const e of edges) {
    adjacent.get(e.source).add(e.target);
    adjacent.get(e.target).add(e.source);
    if (e.source === centerId) toCenter.set(e.target, e.weight);
    if (e.target === centerId) toCenter.set(e.source, e.weight);
  }

  const edgeEls = new Map();
  const edgeLayer = svgEl("g");
  for (const e of edges) {
    const a = byId.get(e.source), b = byId.get(e.target);
    const s = strength(e.weight);
    const line = svgEl("line", {
      class: "edge", x1: a.x.toFixed(1), y1: a.y.toFixed(1), x2: b.x.toFixed(1), y2: b.y.toFixed(1),
      "stroke-width": (0.6 + s * 1.6).toFixed(2),
      style: `opacity:${(0.1 + s * 0.35).toFixed(2)}`,
    });
    edgeEls.set(e, line);
    edgeLayer.append(line);
  }
  svg.append(edgeLayer);

  const nodeEls = new Map(), labelEls = new Map();
  const nodeLayer = svg.appendChild(svgEl("g"));
  const labelLayer = svg.appendChild(svgEl("g"));

  const focus = (id) => {
    svg.classList.add("has-focus");
    const on = new Set([id, ...adjacent.get(id)]);
    nodeEls.forEach((g, nid) => g.classList.toggle("on", on.has(nid)));
    labelEls.forEach((t, nid) => t.classList.toggle("on", on.has(nid)));
    edgeEls.forEach((line, e) => line.classList.toggle("on", e.source === id || e.target === id));
    showTip(byId.get(id), toCenter.get(id));
  };
  const unfocus = () => {
    svg.classList.remove("has-focus");
    hideTip();
  };

  const nodeRadius = (n) => (n.ring === 0 ? 11 : n.ring === 1 ? 7 : 4.5);

  for (const n of nodes) {
    const radius = nodeRadius(n);
    const g = svgEl("g", {
      class: `node r${n.ring}`, role: "button", "aria-label": `Open ${n.title}`,
      tabindex: n.ring === 2 ? "-1" : "0",
    }, svgEl("circle", { cx: n.x.toFixed(1), cy: n.y.toFixed(1), r: radius }));

    if (n.ring !== 0) {
      g.addEventListener("click", () => openMovie(n.id));
      g.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openMovie(n.id); }
      });
    }
    g.addEventListener("pointerenter", () => focus(n.id));
    g.addEventListener("pointerleave", unfocus);
    g.addEventListener("focus", () => focus(n.id));
    g.addEventListener("blur", unfocus);
    nodeEls.set(n.id, g);
    nodeLayer.append(g);

  }

  // Names for the movie itself and its direct neighbours, strongest first. A name
  // is skipped if it would overlap one already placed (it still shows on hover).
  const placed = [];
  const narrow = window.matchMedia("(max-width: 560px)").matches;
  const fontSize = narrow ? 22 : 12.5;      // the SVG is scaled down on phones, so draw text bigger
  const maxChars = narrow ? 16 : 26;
  const labelOrder = nodes
    .filter((n) => n.ring <= 1)
    .sort((a, b) => (a.ring - b.ring) || ((toCenter.get(b.id) || 0) - (toCenter.get(a.id) || 0)));

  for (const n of labelOrder) {
    const radius = nodeRadius(n);
    const text = shorten(n.title, maxChars);
    const width = text.length * fontSize * 0.53;
    const offset = radius + 7;

    // Candidate positions: pointing away from the centre first, then the other sides.
    const dx = n.x - GW / 2, dy = n.y - GH / 2;
    const outward = n.ring === 0 ? "below" : Math.abs(dx) > Math.abs(dy) * 0.6 ? (dx > 0 ? "right" : "left") : dy > 0 ? "below" : "above";
    const sides = [outward, ...["right", "left", "below", "above"].filter((s) => s !== outward)];

    for (const side of sides) {
      const anchor = side === "right" ? "start" : side === "left" ? "end" : "middle";
      const x = n.x + (side === "right" ? offset : side === "left" ? -offset : 0);
      const y = side === "below" ? n.y + radius + fontSize + 4 : side === "above" ? n.y - radius - 8 : n.y + fontSize * 0.32;
      const left = anchor === "start" ? x : anchor === "end" ? x - width : x - width / 2;
      const box = { l: left - 4, r: left + width + 4, t: y - fontSize, b: y + fontSize * 0.4 };

      const inside = box.l > 8 && box.r < GW - 8 && box.t > 4 && box.b < GH - 4;
      const hitsLabel = placed.some((p) => box.l < p.r && box.r > p.l && box.t < p.b && box.b > p.t);
      const hitsDot = nodes.some((m) => m !== n && m.x > box.l - 5 && m.x < box.r + 5 && m.y > box.t - 5 && m.y < box.b + 5);
      if (n.ring > 0 && (!inside || hitsLabel || hitsDot)) continue;

      placed.push(box);
      const label = svgEl("text", { x: x.toFixed(1), y: y.toFixed(1), "text-anchor": anchor, class: "label", style: `font-size:${fontSize}px` }, text);
      labelEls.set(n.id, label);
      labelLayer.append(label);
      break;
    }
  }

  // Text list: the same web for keyboard and screen-reader users.
  const closest = nodes.filter((n) => n.ring === 1).sort((a, b) => (toCenter.get(b.id) || 0) - (toCenter.get(a.id) || 0));
  const further = nodes.filter((n) => n.ring === 2);
  const item = (n, right) => el("li", {}, el("button", { type: "button", onclick: () => openMovie(n.id) },
    el("span", {}, n.title), el("span", { class: "pct" }, right)));
  $("#similar").append(...closest.map((n) => item(n, `${toCenter.get(n.id)}%`)));
  $("#similar-outer").append(...further.map((n) => item(n, n.year ? String(n.year) : "")));
}
