<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { CalendarDays, Check, ClipboardList, Copy, FileText, FolderOpen, GripVertical, ImagePlus, LoaderCircle, MapPin, Palette, Plus, RefreshCw, Save, Search, Sparkles, Trash2, WandSparkles, X, ZoomIn } from "@lucide/vue";
import { api } from "./api";
import PhotoLightbox from "./PhotoLightbox.vue";
import { dateRange, editPhoto, imageUrl, localDate, movePhoto, nextPublishDate, splitLocations } from "./compositions";
import type { CompositionDate, CompositionGroup, CompositionPhoto, FilterPreset } from "./compositions";

const groups = ref<CompositionGroup[]>([]);
const dates = ref<CompositionDate[]>([]);
const presets = ref<FilterPreset[]>([]);
const presetNames = ref<Record<string, string>>({});
const sourcePhotos = ref<Record<string, CompositionPhoto[]>>({});
const loadingDates = ref<string[]>([]);
const selectedDates = ref<string[]>([]);
const photos = ref<CompositionPhoto[]>([]);
const current = ref<CompositionGroup | null>(null);
const title = ref("");
const location = ref("");
const captionTitle = ref("");
const caption = ref("");
const autoPublishDate = ref(true);
const manualPublishDate = ref("");
const draftCreatedDate = ref(localDate());
const autoTime = ref(true);
const autoCities = ref(true);
const manualStart = ref("");
const manualEnd = ref("");
const manualCities = ref("");
const search = ref("");
const activeId = ref("");
const loading = ref(true);
const saving = ref(false);
const problem = ref("");
const notice = ref("");
const baseline = ref("");
const confirmDelete = ref(false);
const agent = ref<{ directory: string; requestFile: string; prompt: string } | null>(null);
const previewIndex = ref<number | null>(null);
const previewPhotos = ref<CompositionPhoto[]>([]);
const previewIsGroup = ref(false);
const previewStrength = ref(100);
let previewTimer: ReturnType<typeof setTimeout> | undefined;
const draggedId = ref("");
const dropTarget = ref<{ id: string; after: boolean } | null>(null);
const sortNotice = ref("");
let requestId = 0;

const allDates = computed(() => {
  const map = new Map(dates.value.map(day => [day.captureDate, day]));
  for (const day of current.value?.days || []) if (!map.has(day.captureDate)) map.set(day.captureDate, day);
  return [...map.values()].sort((a, b) => b.date.localeCompare(a.date));
});
const visibleDates = computed(() => allDates.value.filter(day => `${day.date} ${day.cities.join(" ")} ${day.places.join(" ")}`.includes(search.value.trim())));
const chosenDays = computed(() => allDates.value.filter(day => selectedDates.value.includes(day.captureDate)));
const automaticDates = computed(() => [...new Set(chosenDays.value.map(day => day.date))].sort());
const automaticCities = computed(() => [...new Set(chosenDays.value.flatMap(day => day.cities))].join("，"));
const startValue = computed({ get: () => autoTime.value ? automaticDates.value[0] || "" : manualStart.value, set: value => { manualStart.value = value; } });
const endValue = computed({ get: () => autoTime.value ? automaticDates.value[automaticDates.value.length - 1] || "" : manualEnd.value, set: value => { manualEnd.value = value; } });
const cityValue = computed({ get: () => autoCities.value ? automaticCities.value : manualCities.value, set: value => { manualCities.value = value; } });
const publishDateValue = computed({
  get: () => {
    if (!autoPublishDate.value) return manualPublishDate.value;
    if (current.value?.publishDate && current.value.autoPublishDate !== false) return current.value.publishDate;
    const start = current.value?.createdAt ? localDate(new Date(current.value.createdAt)) : draftCreatedDate.value;
    return nextPublishDate(start, groups.value.filter(group => group.id !== current.value?.id).flatMap(group => group.publishDate ? [group.publishDate] : []));
  },
  set: value => { manualPublishDate.value = value; }
});
const locations = computed(() => splitLocations(chosenDays.value.flatMap(day => day.places)));
const activePhoto = computed(() => photos.value.find(photo => photo.id === activeId.value) || photos.value[0]);
const chosenIds = computed(() => new Set(photos.value.map(photo => photo.id)));
const previewCollection = computed(() => previewIsGroup.value ? photos.value : previewPhotos.value);
const previewPhoto = computed(() => previewIsGroup.value && previewIndex.value !== null ? previewCollection.value[previewIndex.value] : undefined);
const lightboxPhotos = computed(() => previewCollection.value.map((photo, index) => ({ relative_path: photo.relativePath, thumbnail_url: imageUrl(photo), preview_url: imageUrl(photo, "preview", photo.preset, previewIsGroup.value && index === previewIndex.value ? previewStrength.value : photo.strength), capture_time: "", featured: true })));

watch(() => [previewPhoto.value?.id, previewPhoto.value?.preset, previewPhoto.value?.strength] as const, ([id, preset, strength], [previousId, previousPreset]) => {
  clearTimeout(previewTimer);
  if (id !== previousId || preset !== previousPreset) previewStrength.value = strength ?? 100;
  else previewTimer = setTimeout(() => { previewStrength.value = strength ?? 100; }, 150);
});

function payload() {
  return {
    title: title.value, location: location.value, captionTitle: captionTitle.value, caption: caption.value,
    autoPublishDate: autoPublishDate.value,
    ...(!autoPublishDate.value ? { publishDate: manualPublishDate.value } : {}),
    sourceDates: [...selectedDates.value].sort(),
    autoFill: { time: autoTime.value, cities: autoCities.value },
    ...(!autoTime.value ? { time: { start: manualStart.value, end: manualEnd.value } } : {}),
    ...(!autoCities.value ? { cities: splitLocations([manualCities.value]) } : {}),
    photos: photos.value.map(photo => ({ id: photo.id, captureDate: photo.captureDate, relativePath: photo.relativePath, preset: photo.preset, strength: photo.strength })),
    ...(current.value ? { etag: current.value.etag } : {})
  };
}
const dirty = computed(() => baseline.value !== JSON.stringify(payload()));
function clearMessages() { problem.value = ""; notice.value = ""; }
function canLeave() { return !dirty.value || window.confirm("当前图文组有未保存的修改，放弃这些修改？"); }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ""; } }
function dialogKeydown(event: KeyboardEvent) {
  if (!confirmDelete.value && !agent.value) return;
  if (event.key === "Escape") { confirmDelete.value = false; agent.value = null; event.preventDefault(); }
  if (event.key === "Tab") {
    const controls = Array.from(document.querySelectorAll<HTMLElement>(".composition-modal button, .composition-modal textarea"));
    if (!controls.length) return;
    const index = controls.indexOf(document.activeElement as HTMLElement);
    controls[(index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length]?.focus();
    event.preventDefault();
  }
}

async function refreshCatalog() {
  const [catalog, listing] = await Promise.all([
    api<{ dates: CompositionDate[]; presets: FilterPreset[]; presetNames: Record<string, string> }>("/api/compositions/sources"),
    api<{ groups: CompositionGroup[] }>("/api/compositions")
  ]);
  dates.value = catalog.dates;
  presets.value = catalog.presets;
  presetNames.value = catalog.presetNames || {};
  groups.value = listing.groups;
}

async function fetchDay(day: string, force = false) {
  if (!force && sourcePhotos.value[day]) return;
  loadingDates.value.push(day);
  try {
    const source = await api<CompositionDate & { photos: CompositionPhoto[] }>(`/api/compositions/sources/${day}`);
    sourcePhotos.value[day] = source.photos.map(editPhoto);
    if (source.photos.length) {
      dates.value = [...dates.value.filter(item => item.captureDate !== day), { captureDate: source.captureDate, date: source.date, cities: source.cities, places: source.places, count: source.photos.length }];
    }
  } catch (reason) { problem.value = (reason as Error).message; }
  finally { loadingDates.value = loadingDates.value.filter(value => value !== day); }
}

async function toggleDate(day: string) {
  clearMessages();
  if (selectedDates.value.includes(day)) {
    selectedDates.value = selectedDates.value.filter(value => value !== day);
    photos.value = photos.value.filter(photo => photo.captureDate !== day);
  } else {
    selectedDates.value.push(day);
  }
  autoTime.value = true;
  autoCities.value = true;
  if (selectedDates.value.includes(day)) await fetchDay(day, true);
}

function changeTimeMode(event: Event) {
  const enabled = (event.target as HTMLInputElement).checked;
  if (!enabled) { manualStart.value = startValue.value; manualEnd.value = endValue.value; }
  autoTime.value = enabled;
}

function changeCityMode(event: Event) {
  const enabled = (event.target as HTMLInputElement).checked;
  if (!enabled) manualCities.value = cityValue.value;
  autoCities.value = enabled;
}

function changePublishDateMode(event: Event) {
  const enabled = (event.target as HTMLInputElement).checked;
  if (!enabled) manualPublishDate.value = publishDateValue.value;
  autoPublishDate.value = enabled;
}

function applyGroup(loaded: CompositionGroup | null) {
  current.value = loaded;
  clearPhotoDrag();
  title.value = loaded?.title || "";
  location.value = loaded?.location || "";
  captionTitle.value = loaded?.captionTitle || "";
  caption.value = loaded?.caption || "";
  autoPublishDate.value = loaded?.autoPublishDate ?? true;
  manualPublishDate.value = loaded?.publishDate || "";
  if (!loaded) draftCreatedDate.value = localDate();
  selectedDates.value = [...(loaded?.sourceDates || [])];
  autoTime.value = loaded?.autoFill?.time ?? true;
  autoCities.value = loaded?.autoFill?.cities ?? true;
  manualStart.value = loaded?.time.start || "";
  manualEnd.value = loaded?.time.end || "";
  manualCities.value = loaded?.cities.join("，") || "";
  photos.value = loaded?.photos.map(editPhoto) || [];
  activeId.value = photos.value[0]?.id || "";
  baseline.value = JSON.stringify(payload());
  agent.value = null;
  previewIndex.value = null;
}

async function openGroup(group: CompositionGroup | null, force = false) {
  if (!force && (loading.value || saving.value || !canLeave())) return;
  const version = ++requestId;
  loading.value = true;
  clearMessages();
  try {
    const loaded = group ? await api<CompositionGroup>(`/api/compositions/${group.id}`) : null;
    if (version !== requestId) return;
    applyGroup(loaded);
    await Promise.all(selectedDates.value.map(day => fetchDay(day, true)));
  } catch (reason) { if (version === requestId) problem.value = (reason as Error).message; }
  finally { if (version === requestId) loading.value = false; }
}

function togglePhoto(photo: CompositionPhoto) {
  clearMessages();
  if (chosenIds.value.has(photo.id)) photos.value = photos.value.filter(item => item.id !== photo.id);
  else { photos.value.push({ ...photo }); activeId.value = photo.id; }
}

function clearPhotoDrag() { draggedId.value = ""; dropTarget.value = null; }

function startPhotoDrag(event: DragEvent, photo: CompositionPhoto) {
  if (saving.value || photos.value.length < 2) { event.preventDefault(); return; }
  draggedId.value = photo.id;
  activeId.value = photo.id;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", photo.id);
  }
}

function overPhoto(event: DragEvent, photo: CompositionPhoto) {
  if (!draggedId.value || saving.value || draggedId.value === photo.id) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
  dropTarget.value = { id: photo.id, after: event.clientX >= bounds.left + bounds.width / 2 };
}

function leavePhoto(event: DragEvent, photo: CompositionPhoto) {
  if (dropTarget.value?.id === photo.id && !(event.relatedTarget instanceof Node && (event.currentTarget as HTMLElement).contains(event.relatedTarget))) dropTarget.value = null;
}

function dropPhoto(event: DragEvent, photo: CompositionPhoto) {
  if (!draggedId.value) return;
  event.preventDefault();
  overPhoto(event, photo);
  if (!saving.value && dropTarget.value && draggedId.value !== photo.id) {
    const from = photos.value.findIndex(item => item.id === draggedId.value);
    const boundary = photos.value.findIndex(item => item.id === photo.id) + (dropTarget.value.after ? 1 : 0);
    const to = boundary - (from < boundary ? 1 : 0);
    photos.value = movePhoto(photos.value, from, to);
    sortNotice.value = `图片已移至第 ${to + 1} 张`;
  }
  clearPhotoDrag();
}

async function sortWithKeyboard(event: KeyboardEvent, photo: CompositionPhoto) {
  if (saving.value || !event.altKey || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const from = photos.value.findIndex(item => item.id === photo.id);
  const to = event.key === "Home" ? 0 : event.key === "End" ? photos.value.length - 1 : from + (event.key === "ArrowLeft" ? -1 : 1);
  if (to < 0 || to >= photos.value.length) return;
  const control = event.currentTarget as HTMLElement;
  activeId.value = photo.id;
  photos.value = movePhoto(photos.value, from, to);
  sortNotice.value = `图片已移至第 ${to + 1} 张`;
  await nextTick();
  control.focus();
}

function openPreview(photo: CompositionPhoto, collection: CompositionPhoto[], editable = false) {
  previewIsGroup.value = editable;
  previewPhotos.value = collection;
  previewIndex.value = collection.findIndex(item => item.id === photo.id);
}

function addLocation(value: string) {
  const existing = splitLocations([location.value]);
  if (!existing.includes(value)) location.value = [...existing, value].join("，");
}

async function save(): Promise<CompositionGroup | null> {
  if (loading.value || saving.value) return null;
  clearMessages();
  if (!title.value.trim() || !location.value.trim()) { problem.value = "标题和地点必填"; return null; }
  if (!selectedDates.value.length || !photos.value.length) { problem.value = "至少选择一个日期和一张精选照片"; return null; }
  if (!autoPublishDate.value && !manualPublishDate.value) { problem.value = "请选择计划发布日期"; return null; }
  saving.value = true;
  try {
    const saved = await api<CompositionGroup>(current.value ? `/api/compositions/${current.value.id}` : "/api/compositions", {
      method: current.value ? "PUT" : "POST", body: JSON.stringify(payload())
    });
    const focused = activeId.value;
    applyGroup(saved);
    activeId.value = focused;
    groups.value = [saved, ...groups.value.filter(item => item.id !== saved.id)];
    await Promise.all(selectedDates.value.map(day => fetchDay(day, true)));
    notice.value = "图文组已保存";
    return saved;
  } catch (reason) { problem.value = (reason as Error).message; return null; }
  finally { saving.value = false; }
}

async function reload() {
  if (loading.value || saving.value || !canLeave()) return;
  loading.value = true;
  clearMessages();
  try { await refreshCatalog(); sourcePhotos.value = {}; await openGroup(current.value, true); }
  catch (reason) { problem.value = (reason as Error).message; }
  finally { loading.value = false; }
}

async function prepareAgent() {
  const group = dirty.value || !current.value ? await save() : current.value;
  if (!group) return;
  saving.value = true;
  try {
    agent.value = await api(`/api/compositions/${group.id}/agent-request`, { method: "POST", body: JSON.stringify({ etag: group.etag }) });
  } catch (reason) { problem.value = (reason as Error).message; }
  finally { saving.value = false; }
}

async function deleteGroup() {
  if (!current.value) return;
  saving.value = true;
  try {
    const id = current.value.id;
    await api(`/api/compositions/${id}`, { method: "DELETE", body: JSON.stringify({ etag: current.value.etag }) });
    groups.value = groups.value.filter(group => group.id !== id);
    confirmDelete.value = false;
    await openGroup(null, true);
    notice.value = "图文组已移入本地回收目录";
  } catch (reason) { problem.value = (reason as Error).message; }
  finally { saving.value = false; }
}

async function copyPrompt() {
  try { await navigator.clipboard.writeText(agent.value?.prompt || ""); notice.value = "Agent 指令已复制"; }
  catch { problem.value = "剪贴板不可用，请在文本框中选择指令"; }
}

async function copyDirectory() {
  if (!current.value) return;
  clearMessages();
  try { await navigator.clipboard.writeText(current.value.directory); notice.value = "本地目录已复制"; }
  catch { problem.value = "剪贴板不可用，请选择目录文字复制"; }
}

function applyToAll() {
  const active = activePhoto.value;
  if (active) photos.value = photos.value.map(photo => ({ ...photo, preset: active.preset }));
}
watch(dirty, () => { agent.value = null; });
watch(() => Boolean(confirmDelete.value || agent.value), async (open, wasOpen) => {
  if (open && !wasOpen) {
    await nextTick();
    document.querySelector<HTMLElement>(".composition-modal button")?.focus();
  }
});
onMounted(async () => {
  window.addEventListener("beforeunload", beforeUnload);
  window.addEventListener("keydown", dialogKeydown);
  try { await refreshCatalog(); await openGroup(groups.value[0] || null, true); }
  catch (reason) { problem.value = (reason as Error).message; }
  finally { loading.value = false; baseline.value ||= JSON.stringify(payload()); }
});
onDeactivated(() => { previewIndex.value = null; confirmDelete.value = false; agent.value = null; clearPhotoDrag(); });
onBeforeUnmount(() => { window.removeEventListener("beforeunload", beforeUnload); window.removeEventListener("keydown", dialogKeydown); clearTimeout(previewTimer); });
</script>

<template>
  <main class="composition-workspace" :aria-busy="loading || saving">
    <header class="composition-heading">
      <div><h1>图文管理 <span>{{ groups.length }}</span></h1><p>{{ current ? current.title : '新建图文组' }}<i v-if="dirty">未保存</i></p></div>
      <div class="composition-actions">
        <button type="button" class="icon-button" title="重新载入图文组和精选来源" :disabled="saving || loading" @click="reload"><RefreshCw :size="16" /></button>
        <button type="button" class="icon-button danger" title="删除图文组" :disabled="!current || saving" @click="confirmDelete = true"><Trash2 :size="16" /></button>
        <button type="button" class="composition-command" :disabled="saving || loading" @click="openGroup(null)"><Plus :size="16" />新建</button>
        <button type="button" class="composition-command" title="保存后准备本地 Agent 任务；不调用模型、不上传图片" :disabled="saving || loading" @click="prepareAgent"><Sparkles :size="16" />准备文案</button>
        <button type="submit" form="composition-form" class="composition-command primary" :disabled="saving || loading"><LoaderCircle v-if="saving" class="spin" :size="16" /><Save v-else :size="16" />{{ saving ? '保存中' : '保存图文组' }}</button>
      </div>
    </header>
    <div v-if="!loading" class="composition-directory"><FolderOpen :size="14" /><span>本地目录</span><code v-if="current">{{ current.directory }}</code><span v-else class="unsaved">尚未保存</span><button v-if="current" type="button" class="icon-button" title="复制本地目录" @click="copyDirectory"><Copy :size="14" /></button></div>
    <div v-if="problem || notice" class="composition-message" :class="{ failure: problem }" role="status"><span>{{ problem || notice }}</span><button type="button" title="关闭消息" @click="clearMessages"><X :size="15" /></button></div>
    <div v-if="loading" class="composition-loading"><LoaderCircle class="spin" :size="24" /></div>
    <div v-else class="composition-columns">
      <aside class="composition-sidebar">
        <section class="composition-library"><h2><FolderOpen :size="15" />图文组 <span>{{ groups.length }}</span></h2>
          <div class="composition-group-list"><button v-for="group in groups" :key="group.id" class="composition-group" :class="{ active: current?.id === group.id }" type="button" :disabled="saving" @click="openGroup(group)">
            <img v-if="group.photos[0]" :src="group.photos[0].thumbnail" alt="" loading="lazy" /><span><strong>{{ group.title }}</strong><small>{{ group.location }}</small><small>{{ group.photos.length }} 张 · {{ group.time.start }}</small><small v-if="group.publishDate" class="composition-group-publish"><CalendarDays :size="11" />{{ group.publishDate }}</small></span>
          </button><p v-if="!groups.length" class="composition-empty">暂无图文组</p></div>
        </section>
        <section class="composition-date-picker"><h2>精选日期 <span>{{ selectedDates.length }} 已选</span></h2>
          <label class="composition-search"><Search :size="14" /><input v-model="search" type="search" aria-label="搜索精选日期" placeholder="日期、城市、地点" /></label>
          <div class="composition-date-list"><label v-for="day in visibleDates" :key="day.captureDate" :class="{ checked: selectedDates.includes(day.captureDate) }"><input type="checkbox" :checked="selectedDates.includes(day.captureDate)" :disabled="saving" @change="toggleDate(day.captureDate)" /><span><strong>{{ day.date }}</strong><small>{{ day.cities.join('、') || '未标注城市' }}</small></span><small>{{ day.count ?? 0 }} 张</small></label>
          <p v-if="!visibleDates.length" class="composition-empty">没有匹配的精选日期</p></div>
        </section>
      </aside>
      <div class="composition-main">
        <form id="composition-form" class="composition-metadata" @submit.prevent="save">
          <header><h2 class="composition-section-title"><ClipboardList :size="16" />基本信息</h2></header>
          <label>标题 <b>*</b><input v-model="title" required maxlength="140" aria-label="图文组标题" placeholder="图文组标题" :disabled="saving" /></label>
          <label>地点 <b>*</b><input v-model="location" required maxlength="300" aria-label="图文组地点" placeholder="景点、街区或小片区域" :disabled="saving" /></label>
          <div class="composition-info-field"><span>时间</span><div class="composition-date-inputs"><input v-model="startValue" type="date" aria-label="图文开始日期" :required="!autoTime" :disabled="saving || autoTime" /><span>至</span><input v-model="endValue" type="date" aria-label="图文结束日期" :min="startValue" :required="!autoTime" :disabled="saving || autoTime" /></div><label class="composition-auto"><input type="checkbox" :checked="autoTime" :disabled="saving" aria-label="时间自动填写" @change="changeTimeMode" />自动填写</label></div>
          <div class="composition-info-field"><label for="composition-city">城市</label><input id="composition-city" v-model="cityValue" aria-label="图文城市" maxlength="500" :disabled="saving || autoCities" /><label class="composition-auto"><input type="checkbox" :checked="autoCities" :disabled="saving" aria-label="城市自动填写" @change="changeCityMode" />自动填写</label></div>
          <div v-if="locations.length" class="composition-location-hints"><MapPin :size="13" /><button v-for="place in locations" :key="place" type="button" :title="`填入地点：${place}`" :aria-pressed="splitLocations([location]).includes(place)" :class="{ selected: splitLocations([location]).includes(place) }" :disabled="saving" @click="addLocation(place)">{{ place }}</button></div>
        </form>
        <div class="composition-editing">
          <section class="composition-selection"><header><h2 class="composition-section-title"><ImagePlus :size="16" />组内图片 <span>{{ photos.length }}</span></h2></header>
            <p class="sr-only" role="status">{{ sortNotice }}</p>
            <div v-if="photos.length" class="composition-selected-grid">
              <article v-for="(photo, index) in photos" :key="photo.id" class="composition-photo" :data-photo-id="photo.id" :class="{ active: activePhoto?.id === photo.id, dragging: draggedId === photo.id, 'drop-before': dropTarget?.id === photo.id && !dropTarget.after, 'drop-after': dropTarget?.id === photo.id && dropTarget.after }" @dragover="overPhoto($event, photo)" @dragleave="leavePhoto($event, photo)" @drop="dropPhoto($event, photo)">
                <div class="composition-photo-media">
                  <button class="composition-photo-select" type="button" :title="`选中第 ${index + 1} 张图片`" :aria-pressed="activePhoto?.id === photo.id" :draggable="!saving && photos.length > 1" :disabled="saving" @click="activeId = photo.id" @dragstart="startPhotoDrag($event, photo)" @dragend="clearPhotoDrag" @keydown="sortWithKeyboard($event, photo)"><img :src="imageUrl(photo)" :alt="`图文组第 ${index + 1} 张照片`" loading="lazy" :draggable="false" /><span>{{ index + 1 }}</span><Check v-if="activePhoto?.id === photo.id" :size="15" /></button>
                  <button class="composition-photo-zoom" type="button" :title="`放大第 ${index + 1} 张图片`" @click.stop="openPreview(photo, photos, true)" @dragstart.prevent><ZoomIn :size="16" /></button>
                </div>
                <div class="composition-photo-tools"><button type="button" class="composition-drag-handle" :title="`拖动排序第 ${index + 1} 张图片（Alt+左右方向键也可排序）`" :draggable="!saving && photos.length > 1" :disabled="saving || photos.length < 2" @click="activeId = photo.id" @dragstart="startPhotoDrag($event, photo)" @dragend="clearPhotoDrag" @keydown="sortWithKeyboard($event, photo)"><GripVertical :size="14" /></button><span>{{ presetNames[photo.preset] || presets.find(p => p.id === photo.preset)?.name || '旧版滤镜' }}</span><button type="button" title="移出图文组" :disabled="saving" @click="togglePhoto(photo)"><X :size="14" /></button></div>
                <label class="composition-photo-strength"><span>强度</span><output>{{ photo.strength }}%</output><input v-model.number="photo.strength" type="range" min="0" max="100" step="1" :aria-label="`第 ${index + 1} 张滤镜强度`" :disabled="saving || photo.preset === 'original'" /></label>
              </article>
            </div>
            <div v-else class="composition-empty-selection"><ImagePlus :size="30" /><p>尚未选入图片</p></div>
          </section>
          <aside class="composition-inspector">
            <section class="composition-filter"><header><h2 class="composition-section-title"><Palette :size="15" />滤镜 · {{ presets.length }} <span v-if="activePhoto">{{ photos.findIndex(p => p.id === activePhoto.id) + 1 }} / {{ photos.length }}</span></h2><button type="button" title="将当前滤镜应用到整组，保留各图强度" :disabled="!activePhoto || saving" @click="applyToAll"><WandSparkles :size="15" /></button></header>
              <div v-if="activePhoto" class="composition-presets"><button v-for="preset in presets" :key="preset.id" type="button" :class="{ active: activePhoto.preset === preset.id }" :title="preset.name" :aria-label="preset.name" :aria-pressed="activePhoto.preset === preset.id" :disabled="saving" @click="activePhoto.preset = preset.id"><img :src="imageUrl(activePhoto, 'thumb', preset.id, 100)" alt="" loading="lazy" /><span>{{ preset.name }}</span></button></div>
            </section>
            <section class="composition-copy">
              <h2 class="composition-section-title"><FileText :size="15" />文案</h2>
              <div class="composition-publish-field"><label for="composition-publish-date">计划发布日期</label><input id="composition-publish-date" v-model="publishDateValue" form="composition-form" type="date" aria-label="计划发布日期" :required="!autoPublishDate" :disabled="saving || autoPublishDate" /><label class="composition-auto"><input type="checkbox" :checked="autoPublishDate" :disabled="saving" aria-label="计划发布日期自动填写" @change="changePublishDateMode" />自动填写</label></div>
              <label>文案标题<input v-model="captionTitle" maxlength="140" aria-label="文案标题" placeholder="选填" :disabled="saving" /></label><label>文案正文<textarea v-model="caption" maxlength="20000" rows="8" aria-label="文案正文" placeholder="选填" :disabled="saving"></textarea></label>
            </section>
          </aside>
        </div>
        <section class="composition-sources"><header><h2 class="composition-section-title">精选来源 <span>{{ chosenDays.length }} 个日期</span></h2></header>
          <p v-if="!chosenDays.length" class="composition-empty">尚未选择日期</p>
          <section v-for="day in chosenDays" :key="day.captureDate" class="composition-source-day"><header><strong>{{ day.date }}</strong><span>{{ day.cities.join('、') }}</span><small>{{ day.places.join('，') }}</small><LoaderCircle v-if="loadingDates.includes(day.captureDate)" class="spin" :size="15" /></header>
            <div class="composition-source-grid"><article v-for="photo in sourcePhotos[day.captureDate] || []" :key="photo.id" class="composition-source-photo" :class="{ chosen: chosenIds.has(photo.id) }"><button type="button" :title="chosenIds.has(photo.id) ? '取消选择照片' : '选入图文组'" :aria-pressed="chosenIds.has(photo.id)" :disabled="saving" @click="togglePhoto(photo)"><img :src="photo.thumbnail" alt="精选来源照片" loading="lazy" /><span v-if="chosenIds.has(photo.id)"><Check :size="16" /></span></button><button class="composition-source-zoom" type="button" title="放大来源照片" @click="openPreview(photo, sourcePhotos[day.captureDate] || [])"><ZoomIn :size="15" /></button></article></div>
            <button v-if="!sourcePhotos[day.captureDate] && !loadingDates.includes(day.captureDate)" type="button" class="composition-command" @click="fetchDay(day.captureDate)"><RefreshCw :size="14" />重试读取</button>
          </section>
        </section>
      </div>
    </div>
    <PhotoLightbox v-if="previewIndex !== null" v-model:index="previewIndex" :photos="lightboxPhotos" :date="dateRange(chosenDays)" @close="previewIndex = null">
      <template v-if="previewPhoto" #controls>
        <section class="composition-lightbox-editor">
          <header><h2><Palette :size="16" />滤镜</h2><span>{{ presetNames[previewPhoto.preset] || presets.find(p => p.id === previewPhoto?.preset)?.name || '旧版滤镜' }}</span></header>
          <div class="composition-presets" aria-label="大图滤镜"><button v-for="preset in presets" :key="preset.id" type="button" :class="{ active: previewPhoto.preset === preset.id }" :title="preset.name" :aria-label="preset.name" :aria-pressed="previewPhoto.preset === preset.id" :disabled="saving" @click="previewPhoto.preset = preset.id"><img :src="imageUrl(previewPhoto, 'thumb', preset.id, 100)" alt="" loading="lazy" /><span>{{ preset.name }}</span></button></div>
          <label class="composition-lightbox-strength"><span>强度</span><output>{{ previewPhoto.strength }}%</output><input v-model.number="previewPhoto.strength" type="range" min="0" max="100" step="1" aria-label="大图滤镜强度" :disabled="saving || previewPhoto.preset === 'original'" /></label>
        </section>
      </template>
    </PhotoLightbox>
    <Teleport to="body"><div v-if="confirmDelete || agent" class="composition-modal" @click.self="confirmDelete = false; agent = null"><section role="dialog" aria-modal="true" :aria-label="confirmDelete ? '删除图文组' : 'Agent 文案任务'"><header><h2>{{ confirmDelete ? '删除图文组？' : 'Agent 文案任务已准备' }}</h2><button type="button" class="icon-button" title="关闭对话框" @click="confirmDelete = false; agent = null"><X :size="16" /></button></header><template v-if="confirmDelete"><p>{{ current?.title }}</p><footer><button class="composition-command" @click="confirmDelete = false">取消</button><button class="composition-command danger" :disabled="saving" @click="deleteGroup"><Trash2 :size="15" />删除</button></footer></template><template v-else-if="agent"><code>{{ agent.directory }}/{{ agent.requestFile }}</code><textarea :value="agent.prompt" readonly rows="4" aria-label="Agent 指令"></textarea><footer><button class="composition-command primary" @click="copyPrompt"><Copy :size="15" />复制 Agent 指令</button></footer></template></section></div></Teleport>
  </main>
</template>

<style src="./compositions.css"></style>
