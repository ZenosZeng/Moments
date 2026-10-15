<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ChevronLeft, ChevronRight, LoaderCircle, X } from "@lucide/vue";
import type { Photo } from "./types";
import { compactPath } from "./utils";

const props = defineProps<{ photos: Photo[]; index: number; date: string }>();
const emit = defineEmits<{ close: []; "update:index": [index: number] }>();
const photo = computed(() => props.photos[props.index]);
const loading = ref(true);
const failed = ref(false);
let previousOverflow = "";
let previousFocus: HTMLElement | null = null;
const closeButton = ref<HTMLButtonElement | null>(null);

function move(direction: number): void {
  if (props.photos.length) emit("update:index", (props.index + direction + props.photos.length) % props.photos.length);
}

function keydown(event: KeyboardEvent): void {
  if (event.key === "Escape") emit("close");
  else if (event.key === "ArrowLeft") move(-1);
  else if (event.key === "ArrowRight") move(1);
  else if (event.key === "Tab") {
    event.preventDefault();
    const buttons = Array.from(closeButton.value?.closest(".annotation-lightbox")?.querySelectorAll<HTMLButtonElement>("button") || []);
    const active = buttons.findIndex((button) => button === document.activeElement);
    const next = (active + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  } else return;
  event.preventDefault();
}

watch(() => photo.value?.relative_path, () => { loading.value = true; failed.value = false; });
onMounted(() => {
  previousOverflow = document.body.style.overflow;
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  document.body.style.overflow = "hidden";
  window.addEventListener("keydown", keydown);
  closeButton.value?.focus();
});
onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow;
  window.removeEventListener("keydown", keydown);
  previousFocus?.focus();
});
</script>

<template>
  <Teleport to="body">
    <div class="annotation-lightbox" role="dialog" aria-modal="true" :aria-label="`${date} 照片大图`" @click.self="$emit('close')">
      <div class="annotation-lightbox-heading"><span>{{ date }} · {{ index + 1 }} / {{ photos.length }}</span><span v-if="photo">{{ compactPath(photo.relative_path) }}</span></div>
      <button ref="closeButton" class="lightbox-close" title="关闭大图" @click="$emit('close')"><X :size="23" /></button>
      <button v-if="photos.length > 1" class="lightbox-arrow previous" title="上一张照片" @click="move(-1)"><ChevronLeft :size="28" /></button>
      <div v-if="loading && !failed" class="lightbox-loading"><LoaderCircle class="spin" :size="26" /></div>
      <div v-if="failed" class="lightbox-loading">大图读取失败</div>
      <img v-if="photo" :key="photo.relative_path" :src="photo.preview_url" :alt="compactPath(photo.relative_path)" :class="{ pending: loading || failed }" @load="loading = false" @error="failed = true; loading = false" />
      <button v-if="photos.length > 1" class="lightbox-arrow next" title="下一张照片" @click="move(1)"><ChevronRight :size="28" /></button>
    </div>
  </Teleport>
</template>
