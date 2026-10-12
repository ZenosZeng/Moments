const state = {
  overview: null,
  selectedDate: null,
  statusFilter: "all",
  minimumCount: 20,
  footprints: [],
  options: { places: [] },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeText(value) {
  return String(value ?? "");
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("visible"), 2600);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function monthLabel(month) {
  const [year, number] = month.split("-");
  return `${year} 年 ${Number(number)} 月`;
}

function setMonthOptions(months, selected) {
  const select = $("#month-select");
  select.replaceChildren();
  [...months].reverse().forEach((month) => {
    const option = document.createElement("option");
    option.value = month;
    option.textContent = monthLabel(month);
    option.selected = month === selected;
    select.append(option);
  });
  const index = months.indexOf(selected);
  $("#previous-month").disabled = index <= 0;
  $("#next-month").disabled = index < 0 || index >= months.length - 1;
}

async function loadOverview(month = "") {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  const overview = await requestJson(`/api/overview${query}`);
  state.overview = overview;
  setMonthOptions(overview.available_months, overview.selected_month);
  $("#source-status").textContent = `${overview.source_root} · 纳入 ${overview.summary.included.toLocaleString()} 张`;
  $("#stat-month-photos").textContent = overview.summary.month_photos.toLocaleString();
  $("#stat-active-days").textContent = overview.summary.active_days;
  $("#stat-reviewed-days").textContent = overview.summary.reviewed_days;
  $("#stat-peak").textContent = overview.summary.max_day
    ? `${overview.summary.max_day.day} 日 · ${overview.summary.max_day.count} 张`
    : "-";
  $("#chart-caption").textContent = `${monthLabel(overview.selected_month)} · ${overview.summary.active_days} 个拍摄日`;
  renderChart();
  renderHighDays();
  updateRefreshButton(overview.refresh);

  const selectedStillExists = overview.days.some((day) => day.date === state.selectedDate && day.count > 0);
  if (!selectedStillExists) {
    const first = [...overview.days].filter((day) => day.count > 0).sort((a, b) => b.count - a.count)[0];
    state.selectedDate = first?.date || null;
  }
  if (state.selectedDate) await loadDay(state.selectedDate);
  else showEmptyDay();
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function renderChart() {
  const container = $("#chart-container");
  container.replaceChildren();
  const days = state.overview.days;
  const width = 1100;
  const height = 390;
  const margin = { top: 34, right: 22, bottom: 42, left: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxCount = Math.max(1, ...days.map((day) => day.count));
  const yMax = Math.ceil(maxCount * 1.16);
  const slot = plotWidth / days.length;
  const barWidth = Math.max(9, slot * 0.72);
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "每日照片数量柱状图" });

  for (let index = 0; index <= 4; index += 1) {
    const y = margin.top + (plotHeight * index) / 4;
    const value = Math.round(yMax * (1 - index / 4));
    svg.append(svgElement("line", { x1: margin.left, y1: y, x2: width - margin.right, y2: y, class: "chart-grid" }));
    const label = svgElement("text", { x: margin.left - 10, y: y + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = value;
    svg.append(label);
  }
  svg.append(svgElement("line", { x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom, class: "chart-axis" }));

  days.forEach((day, index) => {
    const x = margin.left + index * slot + (slot - barWidth) / 2;
    const barHeight = day.count ? (day.count / yMax) * plotHeight : 0;
    const y = height - margin.bottom - barHeight;
    const group = svgElement("g");
    const bar = svgElement("rect", {
      x, y, width: barWidth, height: Math.max(0, barHeight), rx: 2,
      fill: day.count ? "#287271" : "#e2e6e2",
      class: `chart-bar${day.date === state.selectedDate ? " selected" : ""}`,
      tabindex: day.count ? "0" : "-1",
    });
    const placeNames = day.annotation.places.map((place) => place.name).join("、");
    const title = svgElement("title");
    title.textContent = `${day.date}：${day.count} 张${placeNames ? ` · ${placeNames}` : ""}`;
    bar.append(title);
    if (day.count) {
      const select = () => loadDay(day.date);
      bar.addEventListener("click", select);
      bar.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") select(); });
    }
    group.append(bar);

    if (day.annotation.reviewed && day.count) {
      group.append(svgElement("circle", { cx: x + barWidth / 2, cy: Math.max(12, y - 8), r: 4, fill: "#d9a441" }));
    }
    if (day.count && (day.count >= Math.max(10, maxCount * 0.13) || day.date === state.selectedDate)) {
      const countLabel = svgElement("text", { x: x + barWidth / 2, y: Math.max(12, y - 7), "text-anchor": "middle", class: "chart-count" });
      if (!day.annotation.reviewed) countLabel.textContent = day.count;
      group.append(countLabel);
    }
    const dayLabel = svgElement("text", { x: x + barWidth / 2, y: height - 18, "text-anchor": "middle", class: "chart-label" });
    dayLabel.textContent = day.day;
    group.append(dayLabel);
    svg.append(group);
  });
  container.append(svg);
}

function filteredHighDays() {
  return state.overview.days
    .filter((day) => day.count >= state.minimumCount)
    .filter((day) => state.statusFilter === "all" || (state.statusFilter === "reviewed" ? day.annotation.reviewed : !day.annotation.reviewed))
    .sort((a, b) => b.count - a.count || a.date.localeCompare(b.date));
}

function renderHighDays() {
  const rows = filteredHighDays();
  $("#high-days-count").textContent = `${rows.length} 个日期`;
  const body = $("#high-days-body");
  body.replaceChildren();
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.textContent = "当前筛选条件下没有日期";
    cell.style.color = "#69716c";
    row.append(cell);
    body.append(row);
    return;
  }
  rows.forEach((day) => {
    const row = document.createElement("tr");
    row.classList.toggle("selected", day.date === state.selectedDate);
    const values = [
      day.date,
      `${day.count} 张`,
      day.annotation.places.map((place) => place.name).join("、") || "-",
    ];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    const status = document.createElement("td");
    const dot = document.createElement("i");
    dot.className = `status-dot${day.annotation.reviewed ? " reviewed" : ""}`;
    status.append(dot, document.createTextNode(day.annotation.reviewed ? "已整理" : "未整理"));
    row.append(status);
    row.addEventListener("click", () => loadDay(day.date));
    body.append(row);
  });
}

function showEmptyDay() {
  $("#day-empty").hidden = false;
  $("#day-content").hidden = true;
}

async function loadDay(captureDate) {
  const detail = await requestJson(`/api/days/${captureDate}`);
  state.selectedDate = captureDate;
  $("#day-empty").hidden = true;
  $("#day-content").hidden = false;
  $("#day-title").textContent = captureDate;
  $("#day-photo-count").textContent = `${detail.photo_count} 张照片`;
  const badge = $("#day-status-badge");
  badge.textContent = detail.annotation.reviewed ? "已整理" : "未整理";
  badge.classList.toggle("reviewed", detail.annotation.reviewed);
  $("#places-input").value = detail.annotation.places.map((place) => place.name).join("，");
  $("#note-input").value = detail.annotation.note;
  $("#reviewed-input").checked = detail.annotation.reviewed;
  renderThumbnails(detail);
  renderChart();
  renderHighDays();
}

function renderThumbnails(detail) {
  const grid = $("#thumbnail-grid");
  grid.replaceChildren();
  detail.photos.forEach((photo) => {
    const item = document.createElement("div");
    item.className = "thumbnail-item";
    const image = document.createElement("img");
    image.loading = "lazy";
    image.alt = photo.relative_path;
    image.src = photo.thumbnail_url;
    image.addEventListener("error", () => { item.style.display = "none"; });
    const caption = document.createElement("span");
    caption.textContent = photo.relative_path.split("/").pop();
    item.append(image, caption);
    grid.append(item);
  });
  $("#thumbnail-summary").textContent = detail.photos_total > detail.photos_returned
    ? `显示前 ${detail.photos_returned} 张，共 ${detail.photos_total} 张`
    : `共 ${detail.photos_total} 张`;
}

function splitNames(value) {
  return value.split(/[，,]/).map((item) => item.trim()).filter(Boolean);
}

async function saveCurrent(openNext = false) {
  if (!state.selectedDate) return;
  const payload = {
    places: splitNames($("#places-input").value),
    note: $("#note-input").value,
    reviewed: $("#reviewed-input").checked,
  };
  await requestJson(`/api/days/${state.selectedDate}/annotation`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  showToast("标注已保存");
  const currentDate = state.selectedDate;
  await loadOverview(state.overview.selected_month);
  if (openNext) {
    const next = state.overview.days
      .filter((day) => day.count >= state.minimumCount && !day.annotation.reviewed && day.date > currentDate)
      .sort((a, b) => a.date.localeCompare(b.date))[0]
      || state.overview.days
        .filter((day) => day.count >= state.minimumCount && !day.annotation.reviewed)
        .sort((a, b) => b.count - a.count)[0];
    if (next) await loadDay(next.date);
  }
}

async function loadOptions() {
  state.options = await requestJson("/api/options");
  const fill = (selector, items) => {
    const list = $(selector);
    list.replaceChildren();
    items.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.name;
      list.append(option);
    });
  };
  fill("#places-options", state.options.places);
}

async function loadFootprints() {
  const payload = await requestJson("/api/footprints");
  state.footprints = payload.places;
  renderFootprints();
}

function renderFootprints() {
  const query = $("#footprints-search").value.trim().casefold?.() || $("#footprints-search").value.trim().toLowerCase();
  const rows = state.footprints.filter((place) => {
    const haystack = `${place.name} ${place.years.join(" ")}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  $("#footprints-summary").textContent = `${state.footprints.length} 个地点`;
  $("#footprints-empty").hidden = rows.length > 0;
  const body = $("#footprints-body");
  body.replaceChildren();
  rows.forEach((place) => {
    const row = document.createElement("tr");
    [place.name, place.visit_days, place.photo_count.toLocaleString(), place.years.join("、"), place.last_visit].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    row.addEventListener("click", () => renderFootprintDetail(place));
    body.append(row);
  });
}

function renderFootprintDetail(place) {
  const panel = $("#footprint-detail");
  panel.replaceChildren();
  const title = document.createElement("h3");
  title.textContent = place.name;
  const summary = document.createElement("p");
  summary.textContent = `${place.visit_days} 个到访日 · ${place.photo_count.toLocaleString()} 张照片`;
  const list = document.createElement("ul");
  list.className = "visit-list";
  [...place.dates].reverse().forEach((captureDate) => {
    const item = document.createElement("li");
    const dateLabel = document.createElement("span");
    dateLabel.textContent = captureDate;
    const open = document.createElement("button");
    open.className = "secondary-button";
    open.type = "button";
    open.textContent = "打开";
    open.addEventListener("click", async () => {
      switchView("timeline");
      await loadOverview(captureDate.slice(0, 7));
      await loadDay(captureDate);
    });
    item.append(dateLabel, open);
    list.append(item);
  });
  panel.append(title, summary, list);
}

function switchView(view) {
  $("#timeline-view").hidden = view !== "timeline";
  $("#footprints-view").hidden = view !== "footprints";
  $$(".tab-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (view === "footprints") loadFootprints().catch((error) => showToast(error.message, true));
}

function updateRefreshButton(status) {
  const button = $("#refresh-button");
  const running = status?.state === "running";
  button.classList.toggle("refreshing", running);
  button.disabled = running;
  button.title = status?.message || "更新照片索引";
}

async function refreshIndex() {
  try {
    const status = await requestJson("/api/index/refresh", { method: "POST" });
    updateRefreshButton(status);
    showToast("照片索引开始更新");
    const timer = setInterval(async () => {
      try {
        const current = await requestJson("/api/index/status");
        updateRefreshButton(current);
        if (current.state !== "running") {
          clearInterval(timer);
          if (current.state === "complete") {
            showToast(current.message);
            await loadOverview();
          } else showToast(current.message, true);
        }
      } catch (error) {
        clearInterval(timer);
        showToast(error.message, true);
      }
    }, 1500);
  } catch (error) {
    showToast(error.message, true);
  }
}

function bindEvents() {
  $("#month-select").addEventListener("change", (event) => loadOverview(event.target.value).catch((error) => showToast(error.message, true)));
  $("#previous-month").addEventListener("click", () => {
    const months = state.overview.available_months;
    const index = months.indexOf(state.overview.selected_month);
    if (index > 0) loadOverview(months[index - 1]).catch((error) => showToast(error.message, true));
  });
  $("#next-month").addEventListener("click", () => {
    const months = state.overview.available_months;
    const index = months.indexOf(state.overview.selected_month);
    if (index < months.length - 1) loadOverview(months[index + 1]).catch((error) => showToast(error.message, true));
  });
  $("#minimum-count").addEventListener("input", (event) => {
    state.minimumCount = Math.max(0, Number(event.target.value) || 0);
    renderHighDays();
  });
  $$("[data-status]").forEach((button) => button.addEventListener("click", () => {
    state.statusFilter = button.dataset.status;
    $$("[data-status]").forEach((item) => item.classList.toggle("active", item === button));
    renderHighDays();
  }));
  $$(".tab-button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#annotation-form").addEventListener("submit", (event) => { event.preventDefault(); saveCurrent(false).catch((error) => showToast(error.message, true)); });
  $("#save-next-button").addEventListener("click", () => saveCurrent(true).catch((error) => showToast(error.message, true)));
  $("#footprints-search").addEventListener("input", renderFootprints);
  $("#refresh-button").addEventListener("click", refreshIndex);
}

async function start() {
  bindEvents();
  try {
    await Promise.all([loadOverview(), loadOptions()]);
  } catch (error) {
    showToast(error.message, true);
    $("#source-status").textContent = error.message;
  }
}

start();
