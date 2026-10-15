// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { api } from "./api";
import { idleTask } from "./useLocalTask";
import type { Annotation, DayDetail, Overview, Photo } from "./types";

vi.mock("./api", async () => {
  const original = await vi.importActual<typeof import("./api")>("./api");
  return { ...original, api: vi.fn() };
});
vi.mock("./TrailsPreview.vue", () => ({ default: { name: "TrailsPreview", render: () => null } }));

async function settle(): Promise<void> {
  for (let count = 0; count < 12; count++) await nextTick();
}
afterEach(() => { vi.useRealTimers(); vi.mocked(api).mockReset(); });

describe("annotation task integration", () => {
  it("exports locally with progress and only exposes current completed ZIP and checksum", async () => {
    vi.useFakeTimers();
    let run = 0;
    let stale = false;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("/api/overview")) return {
        selected_month: "2024-05", available_months: ["2024-05"], days: [],
        source_root: "", source_roots: ["photos"], refresh: idleTask(),
        summary: { month_photos: 0, active_days: 0, annotated_days: 0, featured_days: 0, included: 0, missing: 0 }
      } satisfies Overview;
      if (path === "/api/settings") return { defaultCity: "", availableCities: [] };
      if (path === "/api/index/status" || path === "/api/trails-preview/status") return idleTask();
      if (path === "/api/public-export/refresh") {
        run += 1;
        return { ...idleTask(), state: "running", run_id: run, percent: 25, cache: { reused: 8, pending: 2, total: 10, unit: "张照片" } };
      }
      if (path === "/api/public-export/status") return run === 0 ? idleTask() : {
        ...idleTask(), state: "complete", run_id: run, percent: 100, ready: !stale, stale,
        message: "公开数据包已生成", cache: { reused: 8, pending: 2, total: 10, unit: "张照片" }
      };
      throw new Error(`Unexpected API path: ${path}`);
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp(App);
    app.mount(host);
    try {
      await settle();
      const button = host.querySelectorAll<HTMLButtonElement>(".task-button")[2];
      expect(host.querySelector(".brand strong")?.textContent).toBe("Moments · 方舟旅迹");
      expect(button.textContent).toContain("导出公开产物");
      expect(host.querySelector(".artifact-links")).toBeNull();
      button.click();
      await settle();
      expect(host.querySelectorAll<HTMLButtonElement>(".task-button")[0].disabled).toBe(true);
      expect(host.querySelectorAll(".task-cache")[2].textContent).toContain("缓存 8 · 待更新 2");
      expect(host.querySelector(".artifact-links")).toBeNull();
      expect(vi.mocked(api).mock.calls).toContainEqual(["/api/public-export/refresh", { method: "POST" }]);
      await vi.advanceTimersByTimeAsync(1000);
      await settle();
      expect(Array.from(host.querySelectorAll<HTMLAnchorElement>(".artifact-links a"), link => link.getAttribute("href"))).toEqual([
        "/api/public-export/files/public-data.zip", "/api/public-export/files/public-data.zip.sha256"
      ]);
      stale = true;
      button.click();
      await settle();
      await vi.advanceTimersByTimeAsync(1000);
      await settle();
      expect(host.querySelector(".artifact-links")).toBeNull();
      expect(host.querySelectorAll(".task-progress-label")[2].textContent).toContain("待重新导出");
    } finally {
      app.unmount();
      host.remove();
    }
  });

  it("loads all photos and refreshes index results without replacing unsaved fields or selections", async () => {
    vi.useFakeTimers();
    const annotation: Annotation = {
      date: "2024-05-02", displayDate: "2024-05-02", places: [],
      isPublic: true, featuredPhotos: [], annotated: false
    };
    let indexed = false;
    let started = false;
    const photo = (number: number): Photo => ({
      relative_path: `month/${number}.jpg`, thumbnail_url: `/thumbnail/${number}`,
      preview_url: `/preview/${number}`, capture_time: "", featured: false
    });
    vi.mocked(api).mockImplementation(async (path) => {
      if (path.startsWith("/api/overview")) {
        const count = indexed ? 123 : 120;
        return {
          selected_month: "2024-05", available_months: ["2024-05"],
          days: [{ date: annotation.date, day: 2, count, annotation }],
          source_root: "", source_roots: ["photos"], refresh: idleTask(),
          summary: { month_photos: count, active_days: 1, annotated_days: 0, featured_days: 0, included: count, missing: 0 }
        } satisfies Overview;
      }
      if (path === "/api/settings") return { defaultCity: "", availableCities: [] };
      if (path === "/api/index/refresh") {
        started = true;
        return { ...idleTask(), state: "running", run_id: 1, percent: 10 };
      }
      if (path === "/api/index/status") {
        if (!started) return idleTask();
        indexed = true;
        return { ...idleTask(), state: "complete", run_id: 1, percent: 100, ready: true, message: "索引已更新" };
      }
      if (path === "/api/trails-preview/status" || path === "/api/public-export/status") return idleTask();
      if (path === `/api/days/${annotation.date}?limit=all`) {
        const photos = indexed ? [photo(1), photo(2), photo(3)] : [photo(1), photo(2)];
        return { date: annotation.date, photo_count: photos.length, annotation, photos, photos_returned: photos.length, photos_total: photos.length, offset: 0 } satisfies DayDetail;
      }
      throw new Error(`Unexpected API path: ${path}`);
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp(App);
    app.mount(host);
    try {
      await settle();
      expect(host.querySelectorAll(".task-button")).toHaveLength(3);
      expect(host.querySelector(".bar-count")?.textContent).toBe("120");
      host.querySelector<SVGGElement>(".bar-group")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await settle();
      const inputs = host.querySelectorAll<HTMLInputElement>(".simple-form input");
      inputs[0].value = "杭州";
      inputs[1].value = "公园";
      inputs.forEach((input) => input.dispatchEvent(new Event("input", { bubbles: true })));
      host.querySelector<HTMLButtonElement>('.star-button[title="设为精选"]')!.click();
      await settle();
      expect(host.querySelectorAll(".photo-card")).toHaveLength(2);
      host.querySelector<HTMLButtonElement>(".task-button")!.click();
      await settle();
      await vi.advanceTimersByTimeAsync(1000);
      await settle();
      expect(host.querySelector(".bar-count")?.textContent).toBe("123");
      expect(host.querySelectorAll(".photo-card")).toHaveLength(3);
      expect(inputs[0].value).toBe("杭州");
      expect(inputs[1].value).toBe("公园");
      expect(host.querySelectorAll(".photo-card.featured")).toHaveLength(1);
      expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("limit=60"))).toBe(false);
    } finally {
      app.unmount();
      host.remove();
    }
  });
});
