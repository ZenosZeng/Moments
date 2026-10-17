<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  FileArchive,
  PanelsTopLeft,
  Hash,
  Globe2,
  Image as ImageIcon,
  LoaderCircle,
  MapPinned,
  Save,
  Settings as SettingsIcon,
  Star,
  Trash2,
  X
} from "@lucide/vue";
import { getNames, registerLocale } from "i18n-iso-countries";
import zhCountries from "i18n-iso-countries/langs/zh.json";
import { api, ApiError } from "./api";
import TrailsPreview from "./TrailsPreview.vue";
import TaskControl from "./TaskControl.vue";
import PhotoLightbox from "./PhotoLightbox.vue";
import CompositionManager from "./CompositionManager.vue";
import { useLocalTask } from "./useLocalTask";
import { trailCityColor } from "./trails";
import type {
  Annotation,
  DayDetail,
  Overview,
  Place,
  StudioSettings
} from "./types";
import {
  compactPath,
  CHART_PHOTO_LIMIT,
  chartPhotoCount,
  photoCountColor,
  initialAnnotationCity,
  monthLabel,
  updateFeatured,
  weekendLabel
} from "./utils";

type Footprint = {
  id: string;
  start_date: string;
  end_date: string;
  date_label: string;
  city: string;
  places: string[];
  photo_count: number;
  days: FootprintDay[];
};

type FootprintDay = {
  capture_date: string;
  display_date: string;
  country_code: string;
  country_name: string;
  city: string;
  places: string[];
  photo_count: number;
  place_text: string;
};

type CountryOption = { code: string; name: string };

registerLocale(zhCountries);
const countryOptions: CountryOption[] = Object.entries(getNames("zh"))
  .map(([code, name]) => ({ code, name }))
  .sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));

const overview = ref<Overview | null>(null);
const detail = ref<DayDetail | null>(null);
const form = ref<Annotation | null>(null);
const footprints = ref<Footprint[]>([]);
const studioSettings = ref<StudioSettings>({ defaultCity: "", availableCities: [] });
const view = ref<"timeline" | "places" | "trails" | "compositions" | "settings">("timeline");
const trailsRevision = ref(0);
const selectedDate = ref("");
const busy = ref(false);
const saving = ref(false);
const settingsSaving = ref(false);
const recordSaving = ref("");
const loadedPlaceCountry = ref({ city: "", code: "", name: "" });
const countryDialogCity = ref("");
const countryDialogCode = ref("");
const pendingRecord = ref<FootprintDay | null>(null);
const error = ref("");
const notice = ref("");
const lightboxIndex = ref<number | null>(null);
const indexTask = useLocalTask("/api/index", refreshIndexedView);
const previewTask = useLocalTask("/api/trails-preview", () => {
  trailsRevision.value += 1;
  if (previewTask.status.value.ready) notice.value = previewTask.status.value.message;
});
const exportTask = useLocalTask("/api/public-export", () => {
  if (exportTask.status.value.ready) notice.value = exportTask.status.value.message;
});
const indexStatus = indexTask.status;
const previewStatus = previewTask.status;
const exportStatus = exportTask.status;
const indexProblem = indexTask.problem;
const previewProblem = previewTask.problem;
const exportProblem = exportTask.problem;
const tasksBusy = computed(() =>
  indexTask.pending.value || previewTask.pending.value || exportTask.pending.value ||
  indexStatus.value.state === "running" || previewStatus.value.state === "running" || exportStatus.value.state === "running"
);
watch(view, () => { lightboxIndex.value = null; });

const chartWidth = 1120;
const chartHeight = 276;
const chartTop = 28;
const chartBottom = 54;
const chartTicks = [0, 10, 20, 30, 40, CHART_PHOTO_LIMIT];
const selectedFeatured = computed(() => form.value?.featuredPhotos || []);
const featuredPhotoItems = computed(() =>
  detail.value?.photos.filter((photo) => isFeatured(photo.relative_path)) || []
);
const otherPhotoItems = computed(() =>
  detail.value?.photos.filter((photo) => !isFeatured(photo.relative_path)) || []
);
const currentPlace = computed(() => form.value?.places[0] || null);

function blankPlace(city = ""): Place {
  return {
    name: "",
    city
  };
}

function prepareForm(annotation: Annotation): void {
  const storedPlace = annotation.places[0];
  loadedPlaceCountry.value = {
    city: storedPlace?.city || "",
    code: storedPlace?.countryCode || "",
    name: storedPlace?.countryName || ""
  };
  form.value = cloneAnnotation(annotation);
  if (!form.value.annotated) form.value.isPublic = true;
  if (!form.value.places.length) {
    form.value.places.push(blankPlace(
      initialAnnotationCity(form.value.annotated, studioSettings.value.defaultCity)
    ));
  }
}

function barX(index: number): number {
  const count = overview.value?.days.length || 31;
  return 54 + index * ((chartWidth - 72) / count);
}

function barWidth(): number {
  const count = overview.value?.days.length || 31;
  return Math.max(8, (chartWidth - 72) / count - 5);
}

function barHeight(count: number): number {
  return (chartPhotoCount(count) / CHART_PHOTO_LIMIT) * (chartHeight - chartTop - chartBottom);
}

function yForTick(value: number): number {
  return chartHeight - chartBottom - (value / CHART_PHOTO_LIMIT) * (chartHeight - chartTop - chartBottom);
}

function cloneAnnotation(annotation: Annotation): Annotation {
  return JSON.parse(JSON.stringify(annotation)) as Annotation;
}

async function loadOverview(month = ""): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    const query = month ? `?month=${encodeURIComponent(month)}` : "";
    overview.value = await api<Overview>(`/api/overview${query}`);
  } catch (reason) {
    error.value = (reason as Error).message;
  } finally {
    busy.value = false;
  }
}

async function loadSettings(): Promise<void> {
  try {
    studioSettings.value = await api<StudioSettings>("/api/settings");
  } catch (reason) {
    error.value = (reason as Error).message;
  }
}

async function loadDay(date: string): Promise<void> {
  closeCountryDialog();
  lightboxIndex.value = null;
  selectedDate.value = date;
  busy.value = true;
  error.value = "";
  try {
    const result = await api<DayDetail>(`/api/days/${date}?limit=all`);
    if (selectedDate.value !== date) return;
    detail.value = result;
    prepareForm(detail.value.annotation);
  } catch (reason) {
    error.value = (reason as Error).message;
  } finally {
    busy.value = false;
  }
}

function openDayPhoto(relativePath: string): void {
  const index = detail.value?.photos.findIndex((photo) => photo.relative_path === relativePath) ?? -1;
  if (index >= 0) lightboxIndex.value = index;
}

async function refreshIndexedView(): Promise<void> {
  await loadOverview(overview.value?.selected_month);
  const date = selectedDate.value;
  if (date && detail.value) {
    try {
      const updated = await api<DayDetail>(`/api/days/${date}?limit=all`);
      if (selectedDate.value === date) {
        const activePath = lightboxIndex.value === null ? null : detail.value?.photos[lightboxIndex.value]?.relative_path;
        detail.value = updated;
        if (activePath) {
          const index = updated.photos.findIndex((photo) => photo.relative_path === activePath);
          lightboxIndex.value = index < 0 ? null : index;
        }
      }
    } catch (reason) {
      error.value = (reason as Error).message;
    }
  }
  await connectProducts();
  notice.value = indexStatus.value.message;
}

async function changeMonth(direction: number): Promise<void> {
  if (!overview.value) return;
  const index = overview.value.available_months.indexOf(overview.value.selected_month);
  const next = overview.value.available_months[index + direction];
  if (!next) return;
  selectedDate.value = "";
  detail.value = null;
  form.value = null;
  await loadOverview(next);
}

function saveAnnotation(): void {
  void submitAnnotation();
}

function normalizedCity(value: string): string {
  return value.normalize("NFKC").trim().toLocaleLowerCase("zh-CN");
}

async function submitAnnotation(countryOverride: CountryOption | null = null): Promise<void> {
  if (!form.value || !currentPlace.value) return;
  saving.value = true;
  error.value = "";
  const usesStoredCountry = normalizedCity(currentPlace.value.city) ===
    normalizedCity(loadedPlaceCountry.value.city);
  const countryCode = countryOverride?.code || (
    usesStoredCountry ? loadedPlaceCountry.value.code : ""
  );
  const countryName = countryOverride?.name || (
    usesStoredCountry ? loadedPlaceCountry.value.name : ""
  );
  try {
    const saved = await api<Annotation>(`/api/days/${form.value.date}/annotation`, {
      method: "PUT",
      body: JSON.stringify({
        places: [{
          name: currentPlace.value.name,
          city: currentPlace.value.city,
          countryCode,
          countryName
        }],
        featuredPhotos: form.value.featuredPhotos.map((photo) => ({
          relativePath: photo.relativePath
        })),
        isPublic: form.value.isPublic
      })
    });
    prepareForm(saved);
    if (detail.value) detail.value.annotation = saved;
    await loadOverview(overview.value?.selected_month);
    await connectProducts();
    notice.value = "当日数据和精选照片已保存";
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "COUNTRY_REQUIRED") {
      countryDialogCity.value = String(reason.payload.city || currentPlace.value.city);
      countryDialogCode.value = "";
    } else {
      error.value = (reason as Error).message;
    }
  } finally {
    saving.value = false;
  }
}

function closeCountryDialog(): void {
  countryDialogCity.value = "";
  countryDialogCode.value = "";
  pendingRecord.value = null;
}

function confirmCountry(): void {
  const country = countryOptions.find((item) => item.code === countryDialogCode.value);
  if (!country) return;
  const record = pendingRecord.value;
  closeCountryDialog();
  if (record) {
    void submitRecord(record, country);
  } else {
    void submitAnnotation(country);
  }
}

function togglePhoto(relativePath: string): void {
  if (!form.value || !detail.value) return;
  const photo = detail.value.photos.find((item) => item.relative_path === relativePath);
  if (!photo) return;
  form.value.featuredPhotos = updateFeatured(form.value.featuredPhotos, photo);
}

function isFeatured(relativePath: string): boolean {
  return selectedFeatured.value.some((item) => item.relativePath === relativePath);
}

async function refreshIndex(): Promise<void> {
  if (tasksBusy.value) return;
  await indexTask.start();
  await connectProducts();
}

async function connectProducts(): Promise<void> {
  await Promise.all([previewTask.connect(), exportTask.connect()]);
}

async function generatePreview(): Promise<void> {
  if (tasksBusy.value) return;
  view.value = "trails";
  await previewTask.start();
  await Promise.all([indexTask.connect(), exportTask.connect()]);
}

async function exportPublic(): Promise<void> {
  if (tasksBusy.value) return;
  await exportTask.start();
  await Promise.all([indexTask.connect(), previewTask.connect()]);
}

function recordAnchor(captureDate: string): string {
  return `record-${captureDate}`;
}

function recordJourneyStyle(journey: Footprint): Record<string, string> {
  return { "--journey-color": trailCityColor(journey.city || "未填写城市") };
}

async function showAnnotation(captureDate: string): Promise<void> {
  view.value = "timeline";
  await loadOverview(captureDate.slice(0, 7));
  await loadDay(captureDate);
  await nextTick();
  document.querySelector(".day-workspace")?.scrollIntoView({ block: "start" });
}

async function showPlaces(captureDate = ""): Promise<void> {
  view.value = "places";
  const payload = await api<{ places: Footprint[] }>("/api/footprints");
  footprints.value = payload.places.map((journey) => ({
    ...journey,
    days: journey.days.map((day) => ({
      ...day,
      place_text: day.places.join("，")
    }))
  }));
  if (!captureDate) return;
  await nextTick();
  const target = document.getElementById(recordAnchor(captureDate));
  target?.scrollIntoView({ behavior: "smooth", block: "center" });
  target?.classList.add("record-highlight");
  window.setTimeout(() => target?.classList.remove("record-highlight"), 1800);
}

async function submitRecord(
  day: FootprintDay,
  countryOverride: CountryOption | null = null
): Promise<void> {
  recordSaving.value = day.capture_date;
  error.value = "";
  const country = countryOverride || countryOptions.find(
    (item) => item.code === day.country_code
  );
  try {
    await api<Annotation>(`/api/records/${day.capture_date}`, {
      method: "PATCH",
      body: JSON.stringify({
        displayDate: day.display_date,
        places: [{
          name: day.place_text,
          city: day.city,
          countryCode: country?.code || "",
          countryName: country?.name || ""
        }],
      })
    });
    await connectProducts();
    notice.value = `${day.display_date} 的记录已保存`;
    await showPlaces(day.capture_date);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "COUNTRY_REQUIRED") {
      pendingRecord.value = day;
      countryDialogCity.value = String(reason.payload.city || day.city);
      countryDialogCode.value = "";
    } else {
      error.value = (reason as Error).message;
    }
  } finally {
    recordSaving.value = "";
  }
}

async function deleteRecord(day: FootprintDay): Promise<void> {
  const confirmed = window.confirm(
    `确定删除 ${day.display_date} 的标注和精选状态吗？原始照片不会被删除。`
  );
  if (!confirmed) return;
  recordSaving.value = day.capture_date;
  error.value = "";
  try {
    await api(`/api/records/${day.capture_date}`, { method: "DELETE" });
    await connectProducts();
    notice.value = `${day.display_date} 的标注已删除，原始照片未改动`;
    await showPlaces();
  } catch (reason) {
    error.value = (reason as Error).message;
  } finally {
    recordSaving.value = "";
  }
}

async function showSettings(): Promise<void> {
  view.value = "settings";
  await loadSettings();
}

async function saveSettings(): Promise<void> {
  settingsSaving.value = true;
  error.value = "";
  try {
    studioSettings.value = await api<StudioSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ defaultCity: studioSettings.value.defaultCity })
    });
    notice.value = studioSettings.value.defaultCity
      ? `城市缺省值已设为${studioSettings.value.defaultCity}`
      : "城市缺省值已清除";
  } catch (reason) {
    error.value = (reason as Error).message;
  } finally {
    settingsSaving.value = false;
  }
}

function showTrails(): void {
  view.value = "trails";
  if (!previewStatus.value.ready && !tasksBusy.value) void generatePreview();
}

onMounted(async () => {
  await Promise.all([loadOverview(), loadSettings(), indexTask.connect(), previewTask.connect(), exportTask.connect()]);
  const query = new URLSearchParams(window.location.search);
  const requestedView = query.get("view");
  if (requestedView === "trails") {
    showTrails();
    return;
  }
  if (requestedView === "places") {
    await showPlaces();
    return;
  }
  if (requestedView === "settings") {
    view.value = "settings";
    return;
  }
  const requestedDate = query.get("date");
  const requestedDay = overview.value?.days.find(
    (day) => day.date === requestedDate && day.count > 0
  );
  if (requestedDay) await loadDay(requestedDay.date);
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand"><ImageIcon :size="20" /><strong>Moments · 拾光录</strong><span>本地照片标注</span></div>
      <nav aria-label="主导航">
        <button :class="{ active: view === 'timeline' }" @click="view = 'timeline'">
          <CalendarDays :size="17" />照片标注
        </button>
        <button :class="{ active: view === 'places' }" @click="showPlaces()">
          <MapPinned :size="17" />记录列表
        </button>
        <button :class="{ active: view === 'trails' }" @click="showTrails">
          <Globe2 :size="17" />旅行预览
        </button>
        <button :class="{ active: view === 'settings' }" @click="showSettings">
          <SettingsIcon :size="17" />设置
        </button>
        <button :class="{ active: view === 'compositions' }" @click="view = 'compositions'">
          <PanelsTopLeft :size="17" />图文管理
        </button>
      </nav>
      <div class="top-actions">
        <span v-if="overview" class="source" :title="overview.source_roots?.join('\n') || overview.source_root"><Database :size="15" />已连接 {{ overview.source_roots?.length || 1 }} 个原图目录</span>
      </div>
    </header>

    <section class="task-toolbar" aria-label="照片处理任务">
      <div class="task-toolbar-inner">
        <TaskControl label="更新照片索引" kind="index" :status="indexStatus" :problem="indexProblem" :disabled="tasksBusy" :pending="indexTask.pending.value" @start="refreshIndex" />
        <TaskControl label="生成旅行预览" kind="preview" :status="previewStatus" :problem="previewProblem" :disabled="tasksBusy" :pending="previewTask.pending.value" @start="generatePreview" />
        <TaskControl label="导出公开产物" kind="export" :status="exportStatus" :problem="exportProblem" :disabled="tasksBusy" :pending="exportTask.pending.value" @start="exportPublic">
          <div v-if="exportStatus.ready && exportStatus.state === 'complete'" class="artifact-links">
            <a href="/api/public-export/files/public-data.zip" title="下载公开数据 ZIP" download><FileArchive :size="13" />ZIP</a>
            <a href="/api/public-export/files/public-data.zip.sha256" title="下载 SHA-256 校验文件" download><Hash :size="13" />SHA-256</a>
          </div>
        </TaskControl>
      </div>
    </section>

    <div v-if="error || notice" class="toast" :class="{ error }">
      <CircleAlert v-if="error" :size="17" /><Check v-else :size="17" />
      <span>{{ error || notice }}</span>
      <button title="关闭" @click="error = ''; notice = ''"><X :size="16" /></button>
    </div>

    <main v-if="view === 'timeline'" class="timeline-view">
      <section v-if="overview" class="month-band">
        <div class="month-switcher">
          <button class="icon-button" title="上个月" @click="changeMonth(-1)"><ChevronLeft :size="19" /></button>
          <select :value="overview.selected_month" @change="loadOverview(($event.target as HTMLSelectElement).value)">
            <option v-for="month in overview.available_months" :key="month" :value="month">{{ monthLabel(month) }}</option>
          </select>
          <button class="icon-button" title="下个月" @click="changeMonth(1)"><ChevronRight :size="19" /></button>
        </div>
        <div class="stats">
          <div><strong>{{ overview.summary.month_photos.toLocaleString() }}</strong><span>本月照片</span></div>
          <div><strong>{{ overview.summary.active_days }}</strong><span>拍摄天数</span></div>
          <div><strong>{{ overview.summary.annotated_days }}</strong><span>已标注日期</span></div>
          <div><strong>{{ overview.summary.featured_days }}</strong><span>有精选照片</span></div>
        </div>
      </section>

      <section v-if="overview" class="chart-section" aria-label="每日照片数量">
        <div class="section-heading">
          <div><h1>{{ monthLabel(overview.selected_month) }}</h1><p>点击有照片的日期开始整理</p></div>
          <div class="legend"><span class="dot normal"></span>未标注<span class="dot done"></span>已标注<span class="dot public"></span>有精选</div>
        </div>
        <svg class="chart" :viewBox="`0 0 ${chartWidth} ${chartHeight}`" role="img">
          <g v-for="tick in chartTicks" :key="tick">
            <line x1="48" :y1="yForTick(tick)" :x2="chartWidth - 8" :y2="yForTick(tick)" class="grid-line" />
            <text x="40" :y="yForTick(tick) + 4" text-anchor="end" class="axis-text">{{ tick }}</text>
          </g>
          <g v-for="(day, index) in overview.days" :key="day.date" class="bar-group" @click="day.count && loadDay(day.date)">
            <rect
              :x="barX(index)"
              :y="chartHeight - chartBottom - barHeight(day.count)"
              :width="barWidth()"
              :height="Math.max(day.count ? 2 : 0, barHeight(day.count))"
              :class="['bar', { selected: selectedDate === day.date, annotated: day.annotation.annotated, featured: day.annotation.featuredPhotos.length }]"
              rx="2"
            ><title>{{ day.date }}：{{ day.count }} 张</title></rect>
            <text v-if="day.count" :x="barX(index) + barWidth() / 2" :y="chartHeight - chartBottom - barHeight(day.count) - 7" text-anchor="middle" class="bar-count" :fill="photoCountColor(day.count)" :font-size="Math.min(11, (barWidth() + 2) / (String(day.count).length * .65))">{{ day.count }}</text>
            <text v-if="day.day === 1 || day.day % 2 === 0 || weekendLabel(day.date)" :x="barX(index) + barWidth() / 2" :y="chartHeight - 34" text-anchor="middle" class="day-label">{{ day.day }}</text>
            <text v-if="weekendLabel(day.date)" :x="barX(index) + barWidth() / 2" :y="chartHeight - 18" text-anchor="middle" class="weekend-label">{{ weekendLabel(day.date) }}</text>
            <circle v-if="day.annotation.featuredPhotos.length" :cx="barX(index) + barWidth() / 2" :cy="chartHeight - 7" r="2.5" class="featured-dot" />
          </g>
        </svg>
      </section>

      <div v-if="busy && !detail" class="loading"><LoaderCircle class="spin" :size="24" />正在读取照片索引</div>
      <section v-else-if="detail && form" class="day-workspace">
        <div class="editor">
          <div class="editor-title">
            <div><span>{{ detail.date }}</span><h2>{{ detail.photo_count }} 张照片</h2></div>
            <span class="featured-count"><Star :size="15" />{{ form.featuredPhotos.length }} 张精选</span>
          </div>

          <div v-if="currentPlace" class="simple-form">
            <label class="field"><span>城市（可选）</span><input v-model="currentPlace.city" placeholder="例如：成都" maxlength="80" /></label>
            <label class="field"><span>地点（可选）</span><input v-model="currentPlace.name" placeholder="例如：西湖" maxlength="80" /></label>
          </div>
          <div class="editor-actions">
            <label class="public-checkbox"><input v-model="form.isPublic" type="checkbox" />允许在旅行网站公开当日数据和精选照片</label>
            <button class="primary-button" :disabled="saving" @click="saveAnnotation"><LoaderCircle v-if="saving" class="spin" :size="17" /><Save v-else :size="17" />保存当日数据</button>
          </div>
        </div>

        <div class="photo-browser">
          <div class="photo-heading">
            <div><h2>当天照片</h2><p>点击星标选择要在旅行网站展示的照片</p></div>
            <span class="photo-selected"><Star :size="16" />已选 {{ form.featuredPhotos.length }} 张</span>
          </div>
          <section v-if="featuredPhotoItems.length" class="featured-photo-section">
            <div class="photo-subheading"><div><Star :size="16" /><h3>精选照片</h3></div><span>{{ featuredPhotoItems.length }} 张</span></div>
            <div class="featured-photo-row">
              <article v-for="photo in featuredPhotoItems" :key="photo.relative_path" class="photo-card featured">
                <button class="photo-open" title="查看大图" @click="openDayPhoto(photo.relative_path)"><img :src="photo.thumbnail_url" :alt="compactPath(photo.relative_path)" loading="lazy" /></button>
                <button class="star-button active" title="取消精选" @click="togglePhoto(photo.relative_path)">
                  <Star :size="19" fill="currentColor" />
                </button>
                <div class="photo-meta"><span :title="photo.relative_path">{{ compactPath(photo.relative_path) }}</span></div>
              </article>
            </div>
          </section>

          <section class="all-photo-section">
            <div class="photo-subheading"><div><ImageIcon :size="16" /><h3>全部照片</h3></div><span>{{ otherPhotoItems.length }} 张未精选</span></div>
            <div v-if="otherPhotoItems.length" class="photo-grid">
              <article v-for="photo in otherPhotoItems" :key="photo.relative_path" class="photo-card">
                <button class="photo-open" title="查看大图" @click="openDayPhoto(photo.relative_path)"><img :src="photo.thumbnail_url" :alt="compactPath(photo.relative_path)" loading="lazy" /></button>
                <button class="star-button" title="设为精选" @click="togglePhoto(photo.relative_path)">
                  <Star :size="19" fill="none" />
                </button>
                <div class="photo-meta"><span :title="photo.relative_path">{{ compactPath(photo.relative_path) }}</span></div>
              </article>
            </div>
            <div v-else class="photo-list-empty">当天照片均已设为精选</div>
          </section>
        </div>
      </section>
      <section v-else class="empty-state"><CalendarDays :size="34" /><h2>选择一个有照片的日期</h2><p>柱状图越高，表示当天拍摄的照片越多。</p></section>
    </main>

    <main v-else-if="view === 'places'" class="places-view">
      <div class="section-heading"><div><h1>记录列表</h1><p>按旅行和日期倒序排列；除照片数外，每一项都可直接修改</p></div></div>
      <div v-if="footprints.length" class="record-list" role="table" aria-label="旅行记录">
        <div class="records-grid records-heading" role="row">
          <span role="columnheader">时间</span><span role="columnheader">国家</span><span role="columnheader">城市</span><span role="columnheader">地点</span><span role="columnheader">照片数</span><span class="sr-only" role="columnheader">操作</span>
        </div>
        <section
          v-for="journey in footprints"
          :key="journey.id"
          class="record-journey-card"
          role="rowgroup"
          :aria-label="`${journey.date_label} ${journey.city || '未填写城市'}`"
          :style="recordJourneyStyle(journey)"
        >
          <div
            v-for="day in journey.days"
            :id="recordAnchor(day.capture_date)"
            :key="day.capture_date"
            class="records-grid record-row"
            role="row"
          >
            <div role="cell"><input v-model="day.display_date" type="date" aria-label="记录日期" /></div>
            <div role="cell">
              <select v-model="day.country_code" aria-label="国家">
                <option value="">未选择</option>
                <option v-for="country in countryOptions" :key="country.code" :value="country.code">{{ country.name }}</option>
              </select>
            </div>
            <div role="cell"><input v-model="day.city" maxlength="80" aria-label="城市" /></div>
            <div role="cell"><input v-model="day.place_text" maxlength="500" aria-label="地点" placeholder="多个地点可用逗号分隔" /></div>
            <div class="photo-fact" role="cell">{{ day.photo_count.toLocaleString() }}</div>
            <div class="record-action" role="cell">
              <button class="icon-button" :disabled="recordSaving === day.capture_date" title="保存这一天" @click="submitRecord(day)">
                <LoaderCircle v-if="recordSaving === day.capture_date" class="spin" :size="16" /><Save v-else :size="16" />
              </button>
              <button class="icon-button" title="打开当天照片标注" @click="showAnnotation(day.capture_date)">
                <ImageIcon :size="16" />
              </button>
              <button class="icon-button danger" :disabled="recordSaving === day.capture_date" title="删除这条标注" @click="deleteRecord(day)">
                <Trash2 :size="16" />
              </button>
            </div>
          </div>
        </section>
      </div>
      <div v-if="!footprints.length" class="empty-state"><MapPinned :size="34" /><h2>还没有地点标注</h2></div>
    </main>

    <main v-else-if="view === 'settings'" class="settings-view">
      <div class="section-heading"><div><h1>设置</h1><p>标注缺省值</p></div></div>
      <section class="settings-panel">
        <label class="field">
          <span>城市缺省值</span>
          <select v-model="studioSettings.defaultCity">
            <option value="">不设置（新日期留空）</option>
            <option v-for="city in studioSettings.availableCities" :key="city" :value="city">{{ city }}</option>
          </select>
        </label>
        <button class="primary-button" :disabled="settingsSaving" @click="saveSettings">
          <LoaderCircle v-if="settingsSaving" class="spin" :size="17" /><Save v-else :size="17" />保存设置
        </button>
      </section>
    </main>

    <TrailsPreview v-else-if="view === 'trails'" :revision="trailsRevision" :ready="previewStatus.ready" :generating="previewStatus.state === 'running' || previewTask.pending.value" @open-record="showPlaces" />
    <KeepAlive><CompositionManager v-if="view === 'compositions'" /></KeepAlive>
    <PhotoLightbox v-if="lightboxIndex !== null && detail" v-model:index="lightboxIndex" :photos="detail.photos" :date="detail.date" @close="lightboxIndex = null" />

    <div v-if="countryDialogCity" class="country-dialog-backdrop" @click.self="closeCountryDialog" @keydown.esc="closeCountryDialog">
      <section class="country-dialog" role="dialog" aria-modal="true" aria-labelledby="country-dialog-title">
        <div class="country-dialog-heading">
          <div><span>需要确认国家</span><h2 id="country-dialog-title">{{ countryDialogCity }}</h2></div>
          <button class="icon-button" title="关闭" @click="closeCountryDialog"><X :size="18" /></button>
        </div>
        <label class="field">
          <span>国家</span>
          <select v-model="countryDialogCode" autofocus>
            <option value="" disabled>请选择国家</option>
            <option v-for="country in countryOptions" :key="country.code" :value="country.code">
              {{ country.name }}（{{ country.code }}）
            </option>
          </select>
        </label>
        <div class="country-dialog-actions">
          <button class="secondary-button" @click="closeCountryDialog">取消</button>
          <button class="primary-button" :disabled="!countryDialogCode || saving" @click="confirmCountry">
            <LoaderCircle v-if="saving" class="spin" :size="17" /><Save v-else :size="17" />保存当日数据
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
