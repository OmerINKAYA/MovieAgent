"use strict";

const ISTANBUL = [41.015, 29.02];
const RING_CIRCUMFERENCE = 2 * Math.PI * 19; // r=19 in the score ring SVG

const els = {
  genre: document.getElementById("genre"),
  useLocation: document.getElementById("useLocation"),
  mapPanel: document.getElementById("mapPanel"),
  mapStatus: document.getElementById("mapStatus"),
  findBtn: document.getElementById("findBtn"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  tpl: document.getElementById("movieCardTpl"),
};

let pickerMap = null;
let pickerMarker = null;
let selectedLocation = null;

// --------------------------------------------------------------------------- //
// Tile layer helper (shared by picker + result maps)
// --------------------------------------------------------------------------- //
function tileLayer() {
  return L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  });
}

// --------------------------------------------------------------------------- //
// Load genres
// --------------------------------------------------------------------------- //
async function loadGenres() {
  try {
    const res = await fetch("/api/genres");
    const data = await res.json();
    els.genre.innerHTML = "";
    for (const g of data.genres) {
      const opt = document.createElement("option");
      opt.value = g.value;
      opt.textContent = g.label;
      els.genre.appendChild(opt);
    }
    if (data.default) els.genre.value = data.default;
  } catch (err) {
    console.error("Failed to load genres", err);
  }
}

// --------------------------------------------------------------------------- //
// Location picker
// --------------------------------------------------------------------------- //
function initPickerMap() {
  if (pickerMap) {
    setTimeout(() => pickerMap.invalidateSize(), 50);
    return;
  }
  pickerMap = L.map("pickerMap", { scrollWheelZoom: false }).setView(ISTANBUL, 11);
  tileLayer().addTo(pickerMap);
  pickerMap.on("click", (e) => {
    const { lat, lng } = e.latlng;
    selectedLocation = { lat, lon: lng };
    if (pickerMarker) pickerMarker.setLatLng(e.latlng);
    else pickerMarker = L.marker(e.latlng).addTo(pickerMap);
    pickerMarker.bindPopup("Selected location").openPopup();
    els.mapStatus.textContent = `✓ Selected: ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    els.mapStatus.classList.add("is-set");
  });
  setTimeout(() => pickerMap.invalidateSize(), 50);
}

els.useLocation.addEventListener("change", () => {
  const on = els.useLocation.checked;
  els.mapPanel.hidden = !on;
  if (on) initPickerMap();
});

// --------------------------------------------------------------------------- //
// Status helpers
// --------------------------------------------------------------------------- //
function showLoading() {
  els.status.hidden = false;
  els.status.innerHTML =
    '<div class="status__loading"><div class="ring"></div>' +
    "<div>Agents are scouting theaters, comparing films, and reading reviews…</div></div>";
}

function showMessage(text, kind) {
  els.status.hidden = false;
  els.status.innerHTML = `<div class="status__msg status__msg--${kind}">${escapeHtml(text)}</div>`;
}

function clearStatus() {
  els.status.hidden = true;
  els.status.innerHTML = "";
}

// --------------------------------------------------------------------------- //
// Submit
// --------------------------------------------------------------------------- //
async function findMovies() {
  const useLocation = els.useLocation.checked;
  if (useLocation && !selectedLocation) {
    showMessage("Please tap your location on the map first.", "warn");
    return;
  }

  els.findBtn.disabled = true;
  els.findBtn.classList.add("is-loading");
  els.results.innerHTML = "";
  showLoading();

  try {
    const res = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        genre: els.genre.value,
        use_location: useLocation,
        location: useLocation ? selectedLocation : null,
      }),
    });
    const data = await res.json();
    if (!data.ok) {
      showMessage(data.error || "Something went wrong.", "error");
      return;
    }
    renderResults(data);
  } catch (err) {
    console.error(err);
    showMessage("Network error — could not reach the server.", "error");
  } finally {
    els.findBtn.disabled = false;
    els.findBtn.classList.remove("is-loading");
  }
}

els.findBtn.addEventListener("click", findMovies);

// --------------------------------------------------------------------------- //
// Rendering
// --------------------------------------------------------------------------- //
function renderResults(data) {
  if (data.location_warning) showMessage(data.location_warning, "warn");
  else clearStatus();

  els.results.innerHTML = "";

  if (!data.movies.length) {
    showMessage("No movie results available.", "warn");
    return;
  }

  for (const movie of data.movies) {
    els.results.appendChild(buildCard(movie));
  }
  els.results.appendChild(buildSummary(data));
}

function buildCard(movie) {
  const node = els.tpl.content.cloneNode(true);
  const card = node.querySelector(".card");

  // Poster
  const posterImg = node.querySelector(".card__poster img");
  if (movie.poster) {
    posterImg.src = movie.poster;
    posterImg.alt = movie.title;
  } else {
    node.querySelector(".card__poster").remove();
  }

  // Title + sentiment badge
  node.querySelector(".card__title").textContent = movie.title;
  const badge = node.querySelector(".badge");
  const sentiment = (movie.sentiment || "unknown").toLowerCase();
  badge.textContent = movie.sentiment || "unknown";
  if (["positive", "mixed", "negative"].includes(sentiment)) {
    badge.classList.add(`badge--${sentiment}`);
  }

  node.querySelector(".card__explanation").textContent = movie.explanation || "";

  // Score ring
  const ringFg = node.querySelector(".score-ring__fg");
  const ringNum = node.querySelector(".score-ring__num");
  if (typeof movie.score === "number") {
    ringNum.textContent = movie.score;
    const pct = Math.max(0, Math.min(10, movie.score)) / 10;
    requestAnimationFrame(() => {
      ringFg.style.strokeDashoffset = String(RING_CIRCUMFERENCE * (1 - pct));
    });
  } else {
    ringNum.textContent = "–";
  }

  // Closest cinemas
  const closestEl = node.querySelector(".card__closest");
  if (movie.closest && movie.closest.length) {
    const nearest = movie.closest[0];
    closestEl.innerHTML = `<strong>Closest:</strong> ${escapeHtml(nearest.cinema)} · ${nearest.distance_km.toFixed(
      1
    )} km`;
  } else {
    closestEl.remove();
  }

  // Expand row
  const expandBtn = node.querySelector(".card__expand");
  const expandLabel = node.querySelector(".card__expand-label");
  const details = node.querySelector(".card__details");
  const venueCount = movie.total_venues || (movie.venues ? movie.venues.length : 0);
  expandLabel.textContent = venueCount
    ? `Showtimes & cinemas (${venueCount})`
    : "No showtimes listed";
  if (!venueCount) {
    expandBtn.disabled = true;
    expandBtn.style.cursor = "default";
  }

  let detailsBuilt = false;
  expandBtn.addEventListener("click", () => {
    if (!venueCount) return;
    const open = details.hidden;
    details.hidden = !open;
    expandBtn.setAttribute("aria-expanded", String(open));
    if (open && !detailsBuilt) {
      buildDetails(details, movie);
      detailsBuilt = true;
    }
  });

  return card;
}

function buildDetails(details, movie) {
  const venuesEl = details.querySelector(".venues");
  const shown = movie.venues || [];

  for (const venue of shown) {
    venuesEl.appendChild(buildVenue(venue));
  }

  const total = movie.total_venues || shown.length;
  if (total > shown.length) {
    const more = document.createElement("div");
    more.className = "venue__more";
    more.textContent = `Showing the ${shown.length} closest of ${total} cinemas.`;
    venuesEl.appendChild(more);
  }
}

function buildVenue(venue) {
  const wrap = document.createElement("div");
  wrap.className = "venue";

  const head = document.createElement("div");
  head.className = "venue__head";
  const name = document.createElement("span");
  name.className = "venue__name";
  name.textContent = venue.cinema;
  head.appendChild(name);
  if (typeof venue.distance_km === "number") {
    const dist = document.createElement("span");
    dist.className = "venue__dist";
    dist.textContent = `${venue.distance_km.toFixed(1)} km`;
    head.appendChild(dist);
  }
  wrap.appendChild(head);

  if (venue.address) {
    const addr = document.createElement("p");
    addr.className = "venue__addr";
    addr.textContent = venue.date ? `${venue.address} · ${venue.date}` : venue.address;
    wrap.appendChild(addr);
  } else if (venue.date) {
    const d = document.createElement("p");
    d.className = "venue__addr";
    d.textContent = venue.date;
    wrap.appendChild(d);
  }

  if (venue.saloons && venue.saloons.length) {
    const list = document.createElement("div");
    list.className = "venue__saloons";
    for (const s of venue.saloons) {
      const row = document.createElement("div");
      row.className = "venue__saloon";
      const label = s.format ? `${s.saloon} (${s.format})` : s.saloon;
      row.innerHTML = `<b>${escapeHtml(label)}</b>`;
      if (s.times && s.times.length) {
        const times = document.createElement("div");
        times.className = "venue__times";
        for (const t of s.times) {
          const chip = document.createElement("span");
          chip.className = "venue__time";
          chip.textContent = t;
          times.appendChild(chip);
        }
        row.appendChild(times);
      }
      list.appendChild(row);
    }
    wrap.appendChild(list);
  }

  // Embedded location map (or a link fallback when coordinates are missing)
  if (venue.lat != null && venue.lon != null) {
    const mapEl = document.createElement("div");
    mapEl.className = "venue__map";
    wrap.appendChild(mapEl);
    renderVenueMap(mapEl, venue);
  }

  const link = document.createElement("a");
  link.className = "venue__link";
  link.href = venue.map_link;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "Open in OpenStreetMap ↗";
  wrap.appendChild(link);

  return wrap;
}

function renderVenueMap(el, venue) {
  const map = L.map(el, { scrollWheelZoom: false }).setView([venue.lat, venue.lon], 15);
  tileLayer().addTo(map);
  const dist =
    typeof venue.distance_km === "number" ? `<br>${venue.distance_km.toFixed(2)} km away` : "";
  L.marker([venue.lat, venue.lon])
    .addTo(map)
    .bindPopup(`<strong>${escapeHtml(venue.cinema)}</strong><br>${escapeHtml(venue.address || "")}${dist}`);
  setTimeout(() => map.invalidateSize(), 60);
}

function buildSummary(data) {
  const wrap = document.createElement("div");
  wrap.className = "summary";
  const score = typeof data.overall_score === "number" ? data.overall_score : 0;
  wrap.innerHTML = `
    <div class="summary__row">
      <span class="summary__label">Overall score</span>
      <span class="summary__bar"><span class="summary__fill" style="width:0%"></span></span>
      <span class="summary__score">${score}/10</span>
    </div>
    <p class="summary__feedback"><strong>Pipeline feedback:</strong> ${escapeHtml(
      data.pipeline_feedback || "—"
    )}</p>`;
  requestAnimationFrame(() => {
    wrap.querySelector(".summary__fill").style.width = `${(score / 10) * 100}%`;
  });
  return wrap;
}

// --------------------------------------------------------------------------- //
// Utils
// --------------------------------------------------------------------------- //
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

loadGenres();
