import { effectScope } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { idleTask, useLocalTask } from "./useLocalTask";
import type { TaskStatus } from "./types";

vi.mock("./api", async () => {
  const original = await vi.importActual<typeof import("./api")>("./api");
  return { ...original, api: vi.fn() };
});

const mockedApi = vi.mocked(api);
const scopes: ReturnType<typeof effectScope>[] = [];
function controller(onComplete = vi.fn()) {
  const scope = effectScope();
  scopes.push(scope);
  return scope.run(() => useLocalTask("/api/index", onComplete))!;
}
function state(overrides: Partial<TaskStatus>): TaskStatus {
  return { ...idleTask(), run_id: 1, ...overrides };
}
beforeEach(() => { vi.useFakeTimers(); mockedApi.mockReset(); });
afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop());
  vi.useRealTimers();
});

describe("local task polling", () => {
  it("polls progress and invokes completion once per run", async () => {
    const completed = state({ state: "complete", ready: true, percent: 100 });
    mockedApi.mockResolvedValueOnce(state({ state: "running", percent: 0 }))
      .mockResolvedValueOnce(state({ state: "running", percent: 50 }))
      .mockResolvedValue(completed);
    const finished = vi.fn();
    const task = controller(finished);
    await task.start();
    await task.start();
    expect(mockedApi).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(task.status.value.percent).toBe(50);
    await vi.advanceTimersByTimeAsync(1000);
    expect(task.status.value.percent).toBe(100);
    expect(finished).toHaveBeenCalledTimes(1);
    await task.connect();
    expect(finished).toHaveBeenCalledTimes(1);
  });

  it("reconnects to running work after page reload without starting another job", async () => {
    mockedApi.mockResolvedValueOnce(state({ state: "running", percent: 65 }))
      .mockResolvedValueOnce(state({ state: "complete", ready: true, percent: 100 }));
    const task = controller();
    await task.connect();
    expect(mockedApi).toHaveBeenCalledWith("/api/index/status");
    expect(task.status.value.percent).toBe(65);
    await vi.advanceTimersByTimeAsync(1000);
    expect(task.status.value.state).toBe("complete");
  });

  it("retains progress through a temporary connection failure and retries polling", async () => {
    mockedApi.mockResolvedValueOnce(state({ state: "running", percent: 40 }))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(state({ state: "complete", ready: true, percent: 100 }));
    const task = controller();
    await task.start();
    await vi.advanceTimersByTimeAsync(1000);
    expect(task.status.value.percent).toBe(40);
    expect(task.problem.value).toBe("offline");
    await vi.advanceTimersByTimeAsync(1000);
    expect(task.problem.value).toBe("");
    expect(task.status.value.state).toBe("complete");
  });

  it("attaches to an already running job after a conflict response", async () => {
    mockedApi.mockRejectedValueOnce(new ApiError(409, { error: "already running" }))
      .mockResolvedValueOnce(state({ state: "running", percent: 20 }));
    const task = controller();
    await task.start();
    expect(task.status.value.state).toBe("running");
    expect(task.problem.value).toBe("");
  });

  it("ignores an older idle response and stops polling when unmounted", async () => {
    let resolveOld!: (value: TaskStatus) => void;
    mockedApi.mockImplementationOnce(() => new Promise<TaskStatus>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(state({ state: "running", percent: 10 }));
    const task = controller();
    const oldRequest = task.connect();
    await task.start();
    resolveOld(idleTask());
    await oldRequest;
    expect(task.status.value.state).toBe("running");
    scopes[0].stop();
    await vi.advanceTimersByTimeAsync(3000);
    expect(mockedApi).toHaveBeenCalledTimes(2);
  });

  it("allows retry after a failed task", async () => {
    mockedApi.mockResolvedValueOnce(state({ state: "error", message: "failed", percent: 30 }))
      .mockResolvedValueOnce(state({ state: "running", run_id: 2, percent: 0 }));
    const task = controller();
    await task.connect();
    expect(task.status.value.message).toBe("failed");
    await task.start();
    expect(task.status.value.run_id).toBe(2);
  });
});
