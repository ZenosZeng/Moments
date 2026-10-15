import { describe, expect, it } from "vitest";
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

describe("local-ui helpers", () => {
  it("caps bar height at 50 without changing the actual count", () => {
    expect(CHART_PHOTO_LIMIT).toBe(50);
    expect(chartPhotoCount(0)).toBe(0);
    expect(chartPhotoCount(25)).toBe(25);
    expect(chartPhotoCount(50)).toBe(50);
    expect(chartPhotoCount(500)).toBe(50);
  });

  it("uses progressively darker count labels", () => {
    const brightness = (count: number) => Number(photoCountColor(count).match(/\d+/)?.[0]);
    expect(brightness(10)).toBeGreaterThan(brightness(50));
    expect(brightness(50)).toBeGreaterThan(brightness(500));
  });
  it("formats Chinese month labels", () => {
    expect(monthLabel("2026-07")).toBe("2026 年 7 月");
  });

  it("marks Saturdays and Sundays using calendar dates", () => {
    expect(weekendLabel("2026-07-18")).toBe("周六");
    expect(weekendLabel("2026-07-19")).toBe("周日");
    expect(weekendLabel("2026-07-20")).toBe("");
  });

  it("leaves a new annotation city empty unless a default was configured", () => {
    expect(initialAnnotationCity(false, "")).toBe("");
    expect(initialAnnotationCity(false, "深圳")).toBe("深圳");
    expect(initialAnnotationCity(true, "深圳")).toBe("");
  });

  it("toggles featured photos without changing the source path", () => {
    const photo = { relative_path: "202607_a/IMG_1.JPG" };
    const selected = updateFeatured([], photo);
    expect(selected).toEqual([
      { relativePath: "202607_a/IMG_1.JPG" }
    ]);
    expect(updateFeatured(selected, photo)).toEqual([]);
  });

  it("shortens only the display path", () => {
    expect(compactPath("a/b/c.jpg")).toBe(".../b/c.jpg");
  });
});
