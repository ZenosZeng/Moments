// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import TrailsPreview from "./TrailsPreview.vue";
import { api } from "./api";
import type { TrailsPreviewData, TrailTrip } from "./types";

vi.mock("./api", () => ({ api: vi.fn() }));

function trip(date: string, city: string, name: string, photoCount: number, captureDate = date): TrailTrip {
  return {
    id: `trip-${date}`, captureDate, date, year: 2024, title: city,
    places: [{ city, name, countryCode: "CN", countryName: "中国", mapPoint: [114, 22] }],
    photos: Array.from({ length: photoCount }, (_, index) => ({
      id: `${date}-${index}`, src: `/large/${date}-${index}`, thumbnail: `/thumb/${date}-${index}`
    }))
  };
}

async function mountPreview(trips: TrailTrip[]) {
  const payload: TrailsPreviewData = {
    trips, warnings: [],
    summary: { tripDays: trips.length, cities: 2, countries: 1, featuredPhotos: trips.reduce((total, day) => total + day.photos.length, 0) }
  };
  vi.mocked(api).mockResolvedValue(payload);
  const onOpenRecord = vi.fn();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp(TrailsPreview, { revision: 0, ready: true, generating: false, onOpenRecord });
  app.mount(host);
  for (let count = 0; count < 12; count++) await nextTick();
  return { host, app, onOpenRecord };
}

afterEach(() => { vi.mocked(api).mockReset(); });

describe("travel preview timeline", () => {
  it("stacks date, city and locations and groups each trip under one node with daily photo rows", async () => {
    const { host, app, onOpenRecord } = await mountPreview([
      trip("2024-05-01", "深圳", "海边", 1, "2024-04-30"),
      trip("2024-05-02", "深圳", "海边、灯塔 公园，博物馆", 3),
      trip("2024-06-01", "上海", "外滩", 2)
    ]);
    try {
      const entries = host.querySelectorAll(".journey-entry");
      const rows = Array.from(host.querySelectorAll(".trip-day-gallery"));
      expect(entries).toHaveLength(2);
      expect(host.querySelectorAll(".journey-node")).toHaveLength(2);
      expect(host.querySelector(".day-branch, .git-rail, .trip-information")).toBeNull();
      expect(rows.map(row => row.querySelector("time")?.getAttribute("datetime"))).toEqual(["2024-06-01", "2024-05-02", "2024-05-01"]);
      expect(rows.map(row => row.querySelectorAll(".trip-gallery img").length)).toEqual([2, 3, 1]);
      const label = rows[1].querySelector(".trip-day-label")!;
      expect(Array.from(label.children, child => child.className)).toEqual(["journey-date", "journey-city", "journey-places"]);
      expect(label.querySelector(".journey-city")?.textContent).toBe("深圳");
      expect(label.querySelector(".journey-places")?.textContent).toBe("海边，灯塔，公园，博物馆");
      rows[2].querySelector<HTMLButtonElement>(".journey-date")!.click();
      expect(onOpenRecord).toHaveBeenLastCalledWith("2024-04-30");
      entries[1].querySelector<HTMLButtonElement>(".journey-node")!.click();
      expect(onOpenRecord).toHaveBeenLastCalledWith("2024-04-30");
      rows[0].querySelector<HTMLButtonElement>(".trip-gallery button")!.click();
      await nextTick();
      expect(host.querySelector('[role="dialog"] img')?.getAttribute("src")).toBe("/large/2024-06-01-0");
      host.querySelector<HTMLButtonElement>(".close-lightbox")!.click();
      await nextTick();
      expect(host.querySelector('[role="dialog"]')).toBeNull();
    } finally {
      app.unmount();
      host.remove();
    }
  });

  it("does not add an empty location line when no location was recorded", async () => {
    const { host, app } = await mountPreview([trip("2024-05-01", "深圳", "", 1)]);
    try {
      expect(host.querySelector(".journey-date time")?.getAttribute("datetime")).toBe("2024-05-01");
      expect(host.querySelector(".journey-city")?.textContent).toBe("深圳");
      expect(host.querySelector(".journey-places")).toBeNull();
    } finally {
      app.unmount();
      host.remove();
    }
  });
});
