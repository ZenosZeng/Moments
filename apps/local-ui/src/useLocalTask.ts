import { onScopeDispose, ref } from "vue";
import { api, ApiError } from "./api";
import type { TaskStatus } from "./types";

export function idleTask(): TaskStatus {
  return {
    state: "idle", run_id: 0, message: "尚未运行", stage: "",
    completed: 0, total: 0, percent: null, elapsed_seconds: 0,
    ready: false, stale: true
  };
}

export function useLocalTask(prefix: string, onComplete: () => Promise<void> | void) {
  const status = ref<TaskStatus>(idleTask());
  const pending = ref(false);
  const problem = ref("");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  let requestVersion = 0;
  let handledRun = -1;

  function isRunning(): boolean {
    return status.value.state === "running";
  }

  function cancelTimer(): void {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  function schedule(): void {
    cancelTimer();
    if (!disposed && isRunning()) timer = setTimeout(connect, 1000);
  }

  async function accept(next: TaskStatus, version: number): Promise<void> {
    if (disposed || version !== requestVersion) return;
    status.value = next;
    problem.value = "";
    if (next.state === "complete" && handledRun !== next.run_id) {
      handledRun = next.run_id;
      await onComplete();
    }
  }

  async function connect(): Promise<void> {
    if (disposed) return;
    const version = ++requestVersion;
    try {
      await accept(await api<TaskStatus>(`${prefix}/status`), version);
    } catch (reason) {
      if (!disposed && version === requestVersion) problem.value = (reason as Error).message;
    } finally {
      schedule();
    }
  }

  async function start(): Promise<void> {
    if (disposed || pending.value || isRunning()) return;
    cancelTimer();
    pending.value = true;
    const version = ++requestVersion;
    try {
      await accept(await api<TaskStatus>(`${prefix}/refresh`, { method: "POST" }), version);
    } catch (reason) {
      if (disposed) return;
      if (reason instanceof ApiError && reason.status === 409) {
        await connect();
        if (!isRunning()) problem.value = reason.message;
      } else {
        problem.value = (reason as Error).message;
      }
    } finally {
      pending.value = false;
      schedule();
    }
  }

  onScopeDispose(() => {
    disposed = true;
    requestVersion += 1;
    cancelTimer();
  });

  return { status, pending, problem, connect, start };
}
