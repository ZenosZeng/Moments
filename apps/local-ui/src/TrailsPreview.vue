<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  LocateFixed,
  MapPin,
  X,
  ZoomIn,
  ZoomOut
} from "@lucide/vue";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { numericToAlpha2 } from "i18n-iso-countries";
import { feature } from "topojson-client";
import world from "world-atlas/countries-110m.json";
import { api } from "./api";
import { anchoredMapZoom, fitMapBounds } from "./mapViewport";
import {
  aggregateCityVisits,
  filterTrailTrips,
  groupTrailSegments,
  normalizedCity,
  normalizeTrailLabels,
  trailCityColor as cityColor
} from "./trails";
import type { TrailSegment } from "./trails";
import type { TrailsPreviewData } from "./types";

const props = defineProps<{ revision: number }>();
const emit = defineEmits<{ openRecord: [captureDate: string] }>();

type CountryProperties = { name: string };
type CountryFeature = Feature<Geometry, CountryProperties>;

const topology = world as unknown as {
  type: "Topology";
  objects: Record<string, object>;
  arcs: unknown[];
};
const countryCollection = feature(
  topology as never,
  topology.objects.countries as never
) as unknown as FeatureCollection<Geometry, CountryProperties>;
const countries = countryCollection.features as CountryFeature[];
const projection = geoNaturalEarth1().fitExtent(
  [[14, 12], [946, 506]],
  countryCollection
);
const path = geoPath(projection);

const data = ref<TrailsPreviewData | null>(null);
const loading = ref(true);
const error = ref("");
const yearFilter = ref("");
const selectedCity = ref("");
const selectedCountryCode = ref("");
const lightboxSegmentId = ref("");
const lightboxIndex = ref<number | null>(null);
const hoveredCity = ref("");
const zoom = ref(1);
const panX = ref(0);
const panY = ref(0);
const dragging = ref(false);
const dragMoved = ref(false);
const dragPoint = ref({ x: 0, y: 0 });
const mapSvg = ref<SVGSVGElement | null>(null);

const years = computed(() =>
  [...new Set(data.value?.trips.map((trip) => trip.year) || [])].sort((a, b) => b - a)
);
const filteredTrips = computed(() =>
  filterTrailTrips(data.value?.trips || [], yearFilter.value)
);
const timelineTrips = computed(() =>
  filterTrailTrips(filteredTrips.value, "", selectedCity.value)
);
const segments = computed(() => groupTrailSegments(timelineTrips.value));
const cityVisits = computed(() => aggregateCityVisits(filteredTrips.value));
const visitedCountryCodes = computed(() => new Set(
  filteredTrips.value.flatMap((trip) =>
    trip.places.map((place) => place.countryCode.trim().toUpperCase()).filter(Boolean)
  )
));
const markers = computed(() =>
  cityVisits.value.flatMap((visit) => {
    const point = projection(visit.point);
    return point ? [{ ...visit, x: point[0], y: point[1] }] : [];
  })
);
const lightboxSegment = computed(() =>
  segments.value.find((segment) => segment.id === lightboxSegmentId.value) || null
);
const filteredPhotoCount = computed(() =>
  timelineTrips.value.reduce((sum, trip) => sum + trip.photos.length, 0)
);
const activePhoto = computed(() =>
  lightboxIndex.value === null ? null : lightboxSegment.value?.photos[lightboxIndex.value] || null
);
const mapTransform = computed(
  () => `translate(${panX.value} ${panY.value}) translate(480 260) scale(${zoom.value}) translate(-480 -260)`
);

function countryId(country: CountryFeature): string {
  return String(country.id || "").padStart(3, "0");
}

function countryCode(country: CountryFeature): string {
  return numericToAlpha2(countryId(country)) || "";
}

function isVisitedCountry(country: CountryFeature): boolean {
  const code = countryCode(country);
  return Boolean(code && visitedCountryCodes.value.has(code));
}

function isSelectedCountry(country: CountryFeature): boolean {
  return Boolean(
    selectedCountryCode.value && countryCode(country) === selectedCountryCode.value
  );
}

async function loadPreview(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api<TrailsPreviewData>("/api/trails-preview");
    closePhoto();
  } catch (reason) {
    error.value = (reason as Error).message;
  } finally {
    loading.value = false;
  }
}

function toggleCity(city: string): void {
  closePhoto();
  selectedCity.value = normalizedCity(selectedCity.value) === normalizedCity(city) ? "" : city;
}

function segmentCity(segment: TrailSegment): string {
  return segment.places.find((place) => place.city)?.city.trim() || "其他";
}

function displayPlaces(places: TrailSegment["places"]): string {
  return normalizeTrailLabels(places.map((place) => place.name)).join("，");
}

function openRecord(captureDate: string): void {
  emit("openRecord", captureDate);
}

function isCitySelected(city: string): boolean {
  return Boolean(
    selectedCity.value && normalizedCity(selectedCity.value) === normalizedCity(city)
  );
}

function markerHaloRadius(city: string, tripDays: number): number {
  const screenRadius = isCitySelected(city) ? 10 : 12 + Math.min(tripDays, 6);
  return screenRadius / zoom.value;
}

function markerCoreRadius(city: string, tripDays: number): number {
  const screenRadius = isCitySelected(city) ? 6 : Math.min(8, 5 + Math.sqrt(tripDays));
  return screenRadius / zoom.value;
}

function timelineStyle(segment: TrailSegment): Record<string, string> {
  return { "--city-color": cityColor(segmentCity(segment)) };
}

function applyMapTransform(transform: { zoom: number; panX: number; panY: number }): void {
  zoom.value = transform.zoom;
  panX.value = transform.panX;
  panY.value = transform.panY;
}

function setZoom(next: number, anchorX = 480, anchorY = 260): void {
  applyMapTransform(anchoredMapZoom(
    { zoom: zoom.value, panX: panX.value, panY: panY.value },
    next,
    anchorX,
    anchorY
  ));
}

function resetMap(): void {
  selectedCountryCode.value = "";
  applyMapTransform({ zoom: 1, panX: 0, panY: 0 });
}

function mapPointFromClient(clientX: number, clientY: number): { x: number; y: number } | null {
  const svg = mapSvg.value;
  const matrix = svg?.getScreenCTM();
  if (!svg || !matrix) return null;
  const point = svg.createSVGPoint();
  point.x = clientX;
  point.y = clientY;
  const local = point.matrixTransform(matrix.inverse());
  return { x: local.x, y: local.y };
}

function zoomMapAtPointer(event: WheelEvent): void {
  const anchor = mapPointFromClient(event.clientX, event.clientY);
  if (!anchor) return;
  setZoom(zoom.value * (event.deltaY < 0 ? 1.35 : 1 / 1.35), anchor.x, anchor.y);
}

function zoomToCountry(country: CountryFeature): void {
  if (dragMoved.value) return;
  const code = countryCode(country);
  if (!code || !visitedCountryCodes.value.has(code)) return;
  selectedCountryCode.value = code;
  applyMapTransform(fitMapBounds(path.bounds(country)));
}

function startDrag(event: PointerEvent): void {
  dragMoved.value = false;
  if (zoom.value === 1) return;
  const point = mapPointFromClient(event.clientX, event.clientY);
  if (!point) return;
  dragging.value = true;
  dragPoint.value = point;
}

function dragMap(event: PointerEvent): void {
  if (!dragging.value || !mapSvg.value) return;
  const point = mapPointFromClient(event.clientX, event.clientY);
  if (!point) return;
  const deltaX = point.x - dragPoint.value.x;
  const deltaY = point.y - dragPoint.value.y;
  if (!dragMoved.value && Math.hypot(deltaX, deltaY) < 0.75) return;
  if (!dragMoved.value) {
    dragMoved.value = true;
    mapSvg.value.setPointerCapture(event.pointerId);
  }
  panX.value += deltaX;
  panY.value += deltaY;
  dragPoint.value = point;
}

function finishDrag(event: PointerEvent): void {
  dragging.value = false;
  if (mapSvg.value?.hasPointerCapture(event.pointerId)) {
    mapSvg.value.releasePointerCapture(event.pointerId);
  }
  if (dragMoved.value) window.setTimeout(() => { dragMoved.value = false; }, 0);
}

function openPhoto(segment: TrailSegment, photoId: string): void {
  const index = segment.photos.findIndex((photo) => photo.id === photoId);
  if (index < 0) return;
  lightboxSegmentId.value = segment.id;
  lightboxIndex.value = index;
  document.body.style.overflow = "hidden";
}

function closePhoto(): void {
  lightboxSegmentId.value = "";
  lightboxIndex.value = null;
  document.body.style.overflow = "";
}

function movePhoto(direction: number): void {
  if (lightboxIndex.value === null || !lightboxSegment.value?.photos.length) return;
  const length = lightboxSegment.value.photos.length;
  lightboxIndex.value = (lightboxIndex.value + direction + length) % length;
}

watch(() => props.revision, loadPreview, { immediate: true });
watch(segments, (items) => {
  if (!items.some((segment) => segment.id === lightboxSegmentId.value)) closePhoto();
});
watch(cityVisits, (visits) => {
  if (
    selectedCity.value &&
    !visits.some((visit) => normalizedCity(visit.name) === normalizedCity(selectedCity.value))
  ) {
    selectedCity.value = "";
    closePhoto();
  }
});
watch(visitedCountryCodes, (codes) => {
  if (selectedCountryCode.value && !codes.has(selectedCountryCode.value)) resetMap();
});
onBeforeUnmount(closePhoto);
</script>

<template>
  <main class="trails-preview">
    <section class="preview-controls">
      <div>
        <span>实时发布效果</span>
        <h1>旅行预览</h1>
      </div>
      <div class="preview-filters">
        <label>年份<select v-model="yearFilter"><option value="">全部年份</option><option v-for="year in years" :key="year" :value="String(year)">{{ year }} 年</option></select></label>
        <button v-if="yearFilter" title="清除筛选" @click="yearFilter = ''"><X :size="17" /></button>
      </div>
    </section>

    <details v-if="data?.warnings.length" class="preview-warnings">
      <summary><CircleAlert :size="16" />{{ data.warnings.length }} 条数据需要处理</summary>
      <p v-for="warning in data.warnings" :key="warning">{{ warning }}</p>
    </details>

    <section class="preview-map" aria-label="城市旅行地图">
      <div class="map-summary">
        <div>
          <span>我的旅行地图</span>
          <h2>
            <span class="map-summary-line">{{ visitedCountryCodes.size }} 个国家</span>
            <span class="map-summary-line">{{ cityVisits.length }} 个城市</span>
          </h2>
        </div>
        <div class="map-summary-metrics">
          <h2>
            <span class="map-summary-line">{{ filteredTrips.length }} 天旅行</span>
            <span class="map-summary-line">{{ segments.length }} 个旅行段</span>
            <span class="map-summary-line">{{ filteredPhotoCount }} 张精选照片</span>
          </h2>
        </div>
      </div>
      <div v-if="loading" class="preview-state">正在生成本地预览</div>
      <div v-else-if="error" class="preview-state error">{{ error }}</div>
      <template v-else>
        <svg
          ref="mapSvg"
          class="preview-world-map"
          :class="{ 'has-city-selection': Boolean(selectedCity) }"
          viewBox="0 0 960 520"
          role="img"
          aria-label="可缩放和拖动的城市旅行地图"
          @wheel.prevent="zoomMapAtPointer"
          @pointerdown="startDrag"
          @pointermove="dragMap"
          @pointerup="finishDrag"
          @pointercancel="finishDrag"
        >
          <g :transform="mapTransform">
            <path class="preview-sphere" :d="path({ type: 'Sphere' }) || ''" />
            <path
              v-for="country in countries"
              :key="countryId(country)"
              :d="path(country) || ''"
              class="preview-country"
              :class="{ visited: isVisitedCountry(country), selected: isSelectedCountry(country) }"
              :tabindex="isVisitedCountry(country) ? 0 : -1"
              :role="isVisitedCountry(country) ? 'button' : undefined"
              :aria-pressed="isVisitedCountry(country) ? isSelectedCountry(country) : undefined"
              @click.stop="zoomToCountry(country)"
              @keydown.enter.prevent="zoomToCountry(country)"
            ><title>{{ country.properties.name }}{{ isVisitedCountry(country) ? '，点击放大' : '' }}</title></path>
            <g
              v-for="marker in markers"
              :key="marker.key"
              class="preview-marker"
              :class="{ selected: isCitySelected(marker.name) }"
              :transform="`translate(${marker.x} ${marker.y})`"
              role="button"
              tabindex="0"
              :aria-pressed="isCitySelected(marker.name)"
              @pointerdown.stop
              @mouseenter="hoveredCity = `${marker.name} · ${marker.tripDays} 个旅行日`"
              @mouseleave="hoveredCity = ''"
              @click.stop="toggleCity(marker.name)"
              @keydown.enter.prevent="toggleCity(marker.name)"
            >
              <circle class="marker-halo" :r="markerHaloRadius(marker.name, marker.tripDays)" :style="{ fill: cityColor(marker.name) }" />
              <circle class="marker-core" vector-effect="non-scaling-stroke" :r="markerCoreRadius(marker.name, marker.tripDays)" :style="{ fill: cityColor(marker.name) }" />
              <text v-if="marker.tripDays > 1" class="marker-count" :y="2.5 / zoom" :style="{ fontSize: `${7 / zoom}px` }">{{ marker.tripDays }}</text>
              <text v-if="zoom >= 4" class="marker-label" :x="10 / zoom" :y="-8 / zoom" :style="{ fontSize: `${10 / zoom}px`, strokeWidth: `${3 / zoom}px` }">{{ marker.name }}</text>
              <title>{{ marker.name }} · {{ marker.tripDays }} 个旅行日</title>
            </g>
          </g>
        </svg>
        <div class="map-tools">
          <button title="放大地图" @click="setZoom(zoom * 1.5)"><ZoomIn :size="18" /></button>
          <button title="缩小地图" @click="setZoom(zoom / 1.5)"><ZoomOut :size="18" /></button>
          <button title="重置地图" @click="resetMap"><LocateFixed :size="18" /></button>
        </div>
        <div class="map-key"><i></i>到访城市 · 数字为旅行日</div>
        <div v-if="hoveredCity" class="city-tooltip">{{ hoveredCity }}</div>
      </template>
    </section>

    <section class="preview-journeys">
      <div class="journey-heading">
        <div><span>旅行时间线</span><h2>{{ selectedCity || yearFilter || "全部年份" }}</h2></div>
        <button v-if="selectedCity" title="显示全部城市" @click="toggleCity(selectedCity)"><X :size="15" />全部城市</button>
      </div>
      <div v-if="!loading && !segments.length" class="preview-empty">
        <MapPin :size="32" /><h2>暂无可预览的旅行记录</h2><p>日期需要允许公开并至少选择一张精选照片。</p>
      </div>
      <div v-else class="git-timeline">
        <article
          v-for="segment in segments"
          :key="segment.id"
          class="git-entry"
          :style="timelineStyle(segment)"
        >
          <div class="git-rail">
            <button v-if="segment.days.length === 1" title="在记录列表中编辑" :aria-label="`编辑 ${segment.days[0].dateLabel} 的记录`" @click="openRecord(segment.days[0].captureDate)"><i></i></button>
          </div>
          <div class="trip-information">
            <div class="trip-primary">
              <time>{{ segment.dateLabel }}</time>
              <strong>{{ segmentCity(segment) }}</strong>
            </div>
            <div v-if="segment.days.length === 1" class="trip-line"><MapPin :size="14" />{{ displayPlaces(segment.places) || '—' }}</div>
          </div>
          <div v-if="segment.days.length > 1" class="trip-day-galleries">
            <section v-for="(day, dayIndex) in segment.days" :key="day.captureDate" class="trip-day-gallery">
              <div class="day-branch">
                <button
                  v-if="dayIndex === segment.days.length - 1"
                  class="journey-root"
                  title="编辑旅行起始日"
                  :aria-label="`编辑旅行起始日 ${day.dateLabel}`"
                  @click="openRecord(day.captureDate)"
                ><i></i></button>
                <button v-if="dayIndex < segment.days.length - 1" class="day-node" title="在记录列表中编辑" :aria-label="`编辑 ${day.dateLabel} 的记录`" @click="openRecord(day.captureDate)"><i></i></button>
              </div>
              <div class="trip-day-content">
                <div class="trip-day-label">
                  <time>{{ day.dateLabel }}</time>
                  <span v-if="displayPlaces(day.places)">{{ displayPlaces(day.places) }}</span>
                </div>
                <div class="trip-gallery">
                  <button v-for="photo in day.photos" :key="photo.id" title="查看大图" @click="openPhoto(segment, photo.id)">
                    <img :src="photo.thumbnail" :alt="segment.title" loading="lazy" />
                  </button>
                </div>
              </div>
            </section>
          </div>
          <div v-else class="trip-gallery">
            <button v-for="photo in segment.photos" :key="photo.id" title="查看大图" @click="openPhoto(segment, photo.id)">
              <img :src="photo.thumbnail" :alt="segment.title" loading="lazy" />
            </button>
          </div>
        </article>
      </div>
    </section>

    <div v-if="activePhoto" class="preview-lightbox" role="dialog" aria-modal="true" @click.self="closePhoto">
      <button class="close-lightbox" title="关闭大图" @click="closePhoto"><X :size="24" /></button>
      <button v-if="lightboxSegment && lightboxSegment.photos.length > 1" class="lightbox-nav previous" title="上一张" @click="movePhoto(-1)"><ChevronLeft :size="28" /></button>
      <img :src="activePhoto.src" :alt="lightboxSegment?.title" />
      <button v-if="lightboxSegment && lightboxSegment.photos.length > 1" class="lightbox-nav next" title="下一张" @click="movePhoto(1)"><ChevronRight :size="28" /></button>
    </div>
  </main>
</template>

<style scoped>
.trails-preview { min-height: calc(100vh - 58px); background: #f7f8f6; }
.preview-controls { min-height: 78px; max-width: 1540px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; gap: 24px; border-bottom: 1px solid #d5dcda; }
.preview-controls span, .journey-heading span, .map-summary span { color: #65746f; font-size: 11px; font-weight: 700; text-transform: uppercase; }
.preview-controls h1 { margin: 3px 0 0; font-size: 21px; }
.preview-filters { display: flex; align-items: end; gap: 9px; }
.preview-filters label { display: grid; gap: 4px; color: #65746f; font-size: 10px; font-weight: 700; }
.preview-filters select { width: 150px; height: 34px; padding: 0 8px; }
.preview-filters button { width: 34px; height: 34px; display: grid; place-items: center; color: #566762; background: white; border: 1px solid #c8d1ce; border-radius: 5px; }
.preview-warnings { max-width: 1492px; margin: 12px auto; padding: 9px 12px; color: #80552b; background: #fff8e9; border: 1px solid #e5d0a3; border-radius: 5px; font-size: 12px; }
.preview-warnings summary { display: flex; align-items: center; gap: 7px; cursor: pointer; font-weight: 700; }.preview-warnings p { margin: 7px 0 0 23px; }
.preview-map { position: relative; height: min(65vh, 640px); min-height: 500px; overflow: hidden; background: #dfe9e8; border-bottom: 1px solid #c4cfcc; }
.map-summary { position: absolute; z-index: 4; left: max(24px, calc((100vw - 1492px) / 2)); right: max(24px, calc((100vw - 1492px) / 2)); top: 22px; display: flex; justify-content: space-between; pointer-events: none; }
.map-summary h2 { margin: 7px 0 0; display: grid; gap: 7px; }.map-summary h2 .map-summary-line { color: #19312d; font-size: 22px; font-weight: 700; line-height: 1.2; text-transform: none; }.map-summary-metrics { padding-top: 18px; text-align: right; }.map-summary-metrics h2 { margin-top: 0; }
.preview-world-map { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }.preview-world-map:active { cursor: grabbing; }
.preview-sphere { fill: #e8f0ef; stroke: #b7c8c4; stroke-width: .7; }.preview-country { fill: #b7c1bd; stroke: #edf2f0; stroke-width: .65; outline: none; vector-effect: non-scaling-stroke; transition: fill 150ms ease; }.preview-country:focus, .preview-country:focus-visible { outline: none; }.preview-country.visited { fill: #92aaa4; cursor: zoom-in; }.preview-country.visited:hover, .preview-country.visited:focus-visible { fill: #718f87; }.preview-country.selected { fill: #c59a43; }
.preview-marker { outline: none; cursor: pointer; transition: opacity 160ms ease; }.preview-world-map.has-city-selection .preview-marker:not(.selected) { opacity: .3; }.marker-halo { opacity: .25; transition: opacity 160ms ease; }.marker-core { stroke: white; stroke-width: 1.8; }.preview-marker:hover .marker-halo { opacity: .38; }.preview-marker:focus-visible .marker-halo { opacity: .12; }.preview-marker:focus-visible .marker-core { stroke: white; stroke-width: 2.2; }.preview-marker.selected .marker-halo { opacity: 0; }.preview-marker.selected:hover .marker-halo { opacity: .1; }.preview-marker.selected .marker-core { stroke: white; stroke-width: 1.8; }.marker-count { fill: white; font-weight: 700; text-anchor: middle; pointer-events: none; }.marker-label { fill: #253d38; font-weight: 700; paint-order: stroke; pointer-events: none; stroke: #eef4f2; stroke-width: 3px; stroke-linejoin: round; }
.map-tools { position: absolute; right: max(22px, calc((100vw - 1492px) / 2)); bottom: 24px; display: grid; overflow: hidden; border: 1px solid #aebdb9; border-radius: 5px; box-shadow: 0 4px 14px #1a322e24; }.map-tools button { width: 36px; height: 35px; display: grid; place-items: center; color: #2b4540; background: #f9fbfa; border: 0; border-bottom: 1px solid #c7d1ce; }.map-tools button:last-child { border-bottom: 0; }
.map-key { position: absolute; left: max(24px, calc((100vw - 1492px) / 2)); bottom: 24px; padding: 8px 10px; display: flex; align-items: center; gap: 7px; color: #52645f; background: #f5f8f5e8; border: 1px solid #c2ceca; border-radius: 5px; font-size: 11px; }.map-key i { width: 10px; height: 10px; background: linear-gradient(135deg, #e05a3f, #16857b, #2f6f9f); border: 2px solid white; border-radius: 50%; box-shadow: 0 0 0 1px #81918c; }.city-tooltip { position: absolute; right: max(72px, calc((100vw - 1390px) / 2)); bottom: 28px; color: #42534e; font-size: 11px; }
.preview-state { height: 100%; display: grid; place-items: center; color: #50615d; }.preview-state.error { color: #9e4237; }
.preview-journeys { max-width: 1540px; margin: 0 auto; padding: 30px 24px 70px; scroll-margin-top: 58px; }.journey-heading { min-height: 58px; display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; border-bottom: 1px solid #d5dcda; }.journey-heading h2 { margin: 4px 0 0; font-size: 21px; }.journey-heading button { height: 32px; padding: 0 10px; display: flex; align-items: center; gap: 6px; color: #52625d; background: white; border: 1px solid #c8d1ce; border-radius: 5px; font-size: 11px; }
.git-timeline { padding-top: 12px; }
.git-entry { position: relative; display: grid; grid-template-columns: 28px 28px minmax(210px, 260px) minmax(0, 1fr); gap: 18px; min-height: 116px; padding: 20px 0; border-bottom: 1px solid #e0e5e3; }
.git-entry:last-child { border-bottom: 0; }
.git-rail { position: relative; grid-column: 1; grid-row: 1; min-height: 76px; }
.git-rail::before { content: ""; position: absolute; z-index: 0; left: 8px; top: -20px; bottom: -20px; width: 3px; background: var(--city-color); opacity: .55; }
.git-entry:first-child .git-rail::before { top: 10px; }
.git-entry:last-child .git-rail::before { bottom: auto; height: 30px; }
.git-entry:only-child .git-rail::before { display: none; }
.git-rail > button { position: absolute; z-index: 2; left: 0; top: 2px; width: 20px; height: 20px; padding: 0; background: transparent; border: 0; border-radius: 50%; }
.git-rail > button i { display: block; width: 17px; height: 17px; margin: 1px; background: var(--city-color); border: 3px solid #f7f8f6; border-radius: 50%; box-shadow: 0 0 0 1px var(--city-color); transition: transform 140ms ease; }
.git-rail > button:hover i, .git-rail > button:focus-visible i { transform: scale(1.16); }
.trip-information { z-index: 1; min-width: 0; grid-column: 3; grid-row: 1; display: grid; align-content: start; gap: 9px; }
.trip-primary { min-width: 0; min-height: 21px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px 11px; }
.trip-primary time { flex: 0 0 auto; color: #74827e; font-size: 11px; }
.trip-primary strong { min-width: 0; color: #233833; font-size: 16px; overflow-wrap: anywhere; }
.trip-line { min-width: 0; display: flex; align-items: flex-start; gap: 7px; color: #60706b; font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
.trip-line svg { flex: 0 0 auto; margin-top: 1px; color: #87948f; }
.trip-day-galleries { min-width: 0; grid-column: 2 / 5; grid-row: 1; display: grid; gap: 11px; }
.trip-day-gallery { min-width: 0; display: grid; grid-template-columns: 28px minmax(210px, 260px) minmax(0, 1fr); gap: 18px; padding-bottom: 11px; border-bottom: 1px solid #e1e6e4; }
.trip-day-gallery:last-child { padding-bottom: 0; border-bottom: 0; }
.day-branch { position: relative; min-height: 42px; }
.day-branch::before { content: ""; position: absolute; left: -18px; top: -12px; bottom: -12px; width: 2px; background: var(--city-color); opacity: .5; }
.trip-day-gallery:last-child .day-branch::after { content: ""; position: absolute; left: -38px; top: -10px; width: 20px; height: 20px; border-right: 2px solid var(--city-color); border-bottom: 2px solid var(--city-color); border-bottom-right-radius: 20px; opacity: .55; }
.trip-day-gallery:first-child .day-branch::before { top: 10px; }
.trip-day-gallery:last-child .day-branch::before { top: -12px; bottom: auto; height: 4px; }
.day-node { position: absolute; z-index: 2; left: -27px; top: 1px; width: 18px; height: 18px; padding: 0; background: transparent; border: 0; border-radius: 50%; }
.day-node i { display: block; width: 14px; height: 14px; margin: 2px; background: #f7f8f6; border: 3px solid var(--city-color); border-radius: 50%; transition: background 140ms ease, transform 140ms ease; }
.day-node:hover i, .day-node:focus-visible i { background: var(--city-color); transform: scale(1.12); }
.journey-root { position: absolute; z-index: 2; left: -47px; top: 0; width: 20px; height: 20px; padding: 0; background: transparent; border: 0; border-radius: 50%; }
.journey-root i { display: block; width: 17px; height: 17px; margin: 1px; background: var(--city-color); border: 3px solid #f7f8f6; border-radius: 50%; box-shadow: 0 0 0 1px var(--city-color); transition: transform 140ms ease; }
.journey-root:hover i, .journey-root:focus-visible i { transform: scale(1.16); }
.trip-day-content { min-width: 0; grid-column: 3; display: grid; grid-template-columns: minmax(0, 140px) minmax(0, 1fr); gap: 12px; }
.trip-day-label { width: 100%; max-width: 140px; min-width: 0; display: grid; align-content: start; gap: 4px; color: #5f6f6a; font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; }
.trip-day-label time { color: #74827e; }
.trip-day-label span { font-weight: 600; }
.trip-gallery { min-width: 0; display: flex; flex-wrap: wrap; align-content: flex-start; gap: 7px; }
.git-entry > .trip-gallery { grid-column: 4; grid-row: 1; }
.trip-gallery button { flex: 0 0 120px; overflow: hidden; padding: 0; background: #dce3e0; border: 0; border-radius: 4px; }
.trip-gallery img { display: block; width: 120px; aspect-ratio: 4/3; object-fit: cover; transition: transform 160ms ease; }
.trip-gallery button:hover img { transform: scale(1.035); }
.preview-empty { min-height: 280px; display: grid; place-content: center; justify-items: center; color: #75827e; }.preview-empty h2 { margin: 10px 0 2px; color: #344640; font-size: 18px; }.preview-empty p { margin: 0; font-size: 12px; }
.preview-lightbox { position: fixed; inset: 0; z-index: 80; padding: 40px 70px; display: grid; place-items: center; background: #0d1312f2; }.preview-lightbox > img { max-width: min(1180px, 86vw); max-height: 84vh; object-fit: contain; }.close-lightbox, .lightbox-nav { position: absolute; display: grid; place-items: center; color: white; background: #24302dbd; border: 1px solid #ffffff38; border-radius: 50%; }.close-lightbox { right: 22px; top: 20px; width: 42px; height: 42px; }.lightbox-nav { top: 50%; width: 44px; height: 44px; }.lightbox-nav.previous { left: 18px; }.lightbox-nav.next { right: 18px; }
</style>
