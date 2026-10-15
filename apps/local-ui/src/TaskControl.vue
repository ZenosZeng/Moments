<script setup lang="ts">
import { computed } from "vue";
import { Download, LoaderCircle, MapPinned, RefreshCw } from "@lucide/vue";
import type { TaskStatus } from "./types";

const props = defineProps<{
  label: string;
  kind: "index" | "preview" | "export";
  status: TaskStatus;
  problem: string;
  disabled: boolean;
  pending: boolean;
}>();
defineEmits<{ start: [] }>();
const running = computed(() => props.pending || props.status.state === "running");
const stale = computed(() => props.status.state === "complete" && !props.status.ready);
const percent = computed(() => stale.value ? 0 : props.status.percent ?? (running.value ? undefined : 0));
const message = computed(() => props.problem || (stale.value ? (props.kind === "export" ? "数据已更新，待重新导出" : "数据已更新，待重新生成") : props.status.message));
const elapsed = computed(() => {
  const seconds = props.status.elapsed_seconds;
  return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
});
</script>

<template>
  <div class="task-control" :class="{ failed: problem || status.state === 'error' }">
    <div class="task-command"><button class="task-button" :disabled="disabled" @click="$emit('start')">
      <LoaderCircle v-if="running" class="spin" :size="17" />
      <RefreshCw v-else-if="kind === 'index'" :size="17" />
      <MapPinned v-else-if="kind === 'preview'" :size="17" />
      <Download v-else :size="17" />
      {{ label }}
    </button><slot /></div>
    <div class="task-progress" :title="message" aria-live="polite">
      <div class="task-progress-label"><span>{{ message }}</span><strong>{{ percent === undefined ? '准备中' : `${percent}%` }}</strong></div>
      <progress :value="percent" max="100" :aria-label="label" />
      <span class="task-elapsed">{{ status.state === 'idle' ? '等待开始' : `已用 ${elapsed}` }}<template v-if="status.total"> · {{ status.completed.toLocaleString() }} / {{ status.total.toLocaleString() }}</template></span>
      <span class="task-cache" :title="status.cache ? `复用 ${status.cache.reused}，待更新 ${status.cache.pending} ${status.cache.unit}` : ''">{{ status.cache ? `缓存 ${status.cache.reused.toLocaleString()} · 待更新 ${status.cache.pending.toLocaleString()} ${status.cache.unit}` : '缓存等待检查' }}</span>
    </div>
  </div>
</template>
