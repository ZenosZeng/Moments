<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  ChevronLeft,
  ChevronRight,
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
import { filterTrips, normalizedCity } from "./filters";
import {
  groupJourneySegments,
  normalizePublicLabels,
  type JourneySegment
} from "./journeys";
import { aggregateCityVisits } from "./map-data";
import { anchoredMapZoom, fitMapBounds } from "./map-viewport";
import type { PublicCityData, PublicData } from "./types";

type CountryProperties = { name: string };
type CountryFeature = Feature<Geometry, CountryProperties>;

const cityPalette = [
  "#e05a3f",
  "#16857b",
  "#2f6f9f",
  "#bd7b16",
  "#8b5fa8",
  "#4f7f45",
  "#c64f70",
  "#5e6fbb"
];

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

const data = ref<PublicData | null>(null);
const cityData = ref<PublicCityData | null>(null);
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
  filterTrips(data.value?.trips || [], yearFilter.value)
);
const timelineTrips = computed(() =>
  filterTrips(filteredTrips.value, "", selectedCity.value)
);
const segments = computed(() => groupJourneySegments(timelineTrips.value));
const cityVisits = computed(() =>
  aggregateCityVisits(filteredTrips.value, cityData.value?.cities || [])
);
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
const filteredPhotoCount = computed(() =>
  timelineTrips.value.reduce((sum, trip) => sum + trip.photos.length, 0)
);
const lightboxSegment = computed(() =>
  segments.value.find((segment) => segment.id === lightboxSegmentId.value) || null
);
const activePhoto = computed(() =>
  lightboxIndex.value === null
    ? null
    : lightboxSegment.value?.photos[lightboxIndex.value] || null
);
const mapTransform = computed(
  () => `translate(${panX.value} ${panY.value}) translate(480 260) scale(${zoom.value}) translate(-480 -260)`
);

function assetUrl(pathname: string): string {
  return `${import.meta.env.BASE_URL}${pathname.replace(/^\//, "")}`;
}

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

function toggleCity(city: string): void {
  closePhoto();
  selectedCity.value = normalizedCity(selectedCity.value) === normalizedCity(city) ? "" : city;
}

function segmentCity(segment: JourneySegment): string {
  return segment.places.find((place) => place.city)?.city.trim() || "其他";
}

function displayPlaces(places: JourneySegment["places"]): string {
  return normalizePublicLabels(places.map((place) => place.name)).join("，");
}

function cityColor(city: string): string {
  const hash = Array.from(normalizedCity(city)).reduce(
    (value, character) => ((value * 31) + (character.codePointAt(0) || 0)) >>> 0,
    0
  );
  return cityPalette[hash % cityPalette.length];
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

function timelineStyle(segment: JourneySegment): Record<string, string> {
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

function openPhoto(segment: JourneySegment, photoId: string): void {
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

function handleWindowKeydown(event: KeyboardEvent): void {
  if (!activePhoto.value) return;
  if (event.key === "Escape") closePhoto();
  if (event.key === "ArrowLeft") movePhoto(-1);
  if (event.key === "ArrowRight") movePhoto(1);
}

function clearFilters(): void {
  yearFilter.value = "";
}

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

onMounted(async () => {
  window.addEventListener("keydown", handleWindowKeydown);
  try {
    const [tripResponse, cityResponse] = await Promise.all([
      fetch(assetUrl("data/trips.json")),
      fetch(assetUrl("data/city-centers.json"))
    ]);
    if (!tripResponse.ok) throw new Error(`公开数据加载失败（${tripResponse.status}）`);
    if (!cityResponse.ok) throw new Error(`城市地图加载失败（${cityResponse.status}）`);
    [data.value, cityData.value] = await Promise.all([
      tripResponse.json() as Promise<PublicData>,
      cityResponse.json() as Promise<PublicCityData>
    ]);
  } catch (reason) {
    error.value = (reason as Error).message;
  } finally {
    loading.value = false;
  }
});

onBeforeUnmount(() => {
  closePhoto();
  window.removeEventListener("keydown", handleWindowKeydown);
});
</script>

<template>
  <main class="trails-preview">
      <section class="preview-controls" aria-labelledby="page-title">
        <div>
          <span>旅行地图与时间线</span>
          <h1 id="page-title">Moments · 拾光录</h1>
        </div>
        <div class="preview-filters">
          <label>
            年份
            <select v-model="yearFilter" aria-label="按年份筛选">
              <option value="">全部年份</option>
              <option v-for="year in years" :key="year" :value="String(year)">{{ year }} 年</option>
            </select>
          </label>
          <button v-if="yearFilter" title="清除筛选" aria-label="清除年份筛选" @click="clearFilters">
            <X :size="17" />
          </button>
        </div>
      </section>

      <section id="map" class="preview-map" aria-label="城市旅行地图">
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
                @keydown.space.prevent="zoomToCountry(country)"
              >
                <title>{{ country.properties.name }}{{ isVisitedCountry(country) ? '，点击放大' : '' }}</title>
              </path>
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
                @keydown.space.prevent="toggleCity(marker.name)"
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
            <button title="放大地图" aria-label="放大地图" @click="setZoom(zoom * 1.5)"><ZoomIn :size="18" /></button>
            <button title="缩小地图" aria-label="缩小地图" @click="setZoom(zoom / 1.5)"><ZoomOut :size="18" /></button>
            <button title="重置地图" aria-label="重置地图" @click="resetMap"><LocateFixed :size="18" /></button>
          </div>
          <div class="map-key"><i></i>到访城市 · 数字为旅行日</div>
          <div v-if="hoveredCity" class="city-tooltip">{{ hoveredCity }}</div>
        </template>
      </section>

      <section class="preview-journeys" aria-labelledby="timeline-title">
        <div class="journey-heading">
          <div><span>旅行时间线</span><h2 id="timeline-title">{{ selectedCity || yearFilter || "全部年份" }}</h2></div>
          <button v-if="selectedCity" title="显示全部城市" @click="toggleCity(selectedCity)"><X :size="15" />全部城市</button>
        </div>
        <div v-if="!loading && !segments.length" class="preview-empty">
          <MapPin :size="32" /><h2>暂无可预览的旅行记录</h2><p>日期需要允许公开并至少选择一张精选照片。</p>
        </div>
        <div v-else class="journey-timeline">
          <article v-for="segment in segments" :key="segment.id" class="journey-entry" :aria-label="`${segment.dateLabel} ${segmentCity(segment)}`" :style="timelineStyle(segment)">
            <div class="journey-rail" aria-hidden="true"><span class="journey-node"><i></i></span></div>
            <div class="trip-day-galleries">
              <section v-for="day in segment.days" :key="day.date" class="trip-day-gallery">
                <div class="trip-day-label">
                  <time class="journey-date" :datetime="day.date">{{ day.dateLabel }}</time>
                  <strong class="journey-city">{{ segmentCity(segment) }}</strong>
                  <span v-if="displayPlaces(day.places)" class="journey-places">{{ displayPlaces(day.places) }}</span>
                </div>
                <div class="trip-gallery">
                  <button v-for="photo in day.photos" :key="photo.id" title="查看大图" @click="openPhoto(segment, photo.id)">
                    <img :src="assetUrl(photo.thumbnail)" :alt="segment.title" loading="lazy" />
                  </button>
                </div>
              </section>
            </div>
          </article>
        </div>
      </section>

    <div v-if="activePhoto" class="preview-lightbox" role="dialog" aria-modal="true" aria-label="精选照片大图" @click.self="closePhoto">
      <button class="close-lightbox" title="关闭大图" aria-label="关闭大图" @click="closePhoto"><X :size="24" /></button>
      <button v-if="lightboxSegment && lightboxSegment.photos.length > 1" class="lightbox-nav previous" title="上一张" aria-label="上一张" @click="movePhoto(-1)"><ChevronLeft :size="28" /></button>
      <img :src="assetUrl(activePhoto.src)" :alt="lightboxSegment?.title" />
      <button v-if="lightboxSegment && lightboxSegment.photos.length > 1" class="lightbox-nav next" title="下一张" aria-label="下一张" @click="movePhoto(1)"><ChevronRight :size="28" /></button>
    </div>
  </main>
</template>
