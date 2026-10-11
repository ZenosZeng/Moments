import { describe, expect, it } from "vitest";
import { anchoredMapZoom, fitMapBounds } from "./map-viewport";

function screenX(contentX: number, zoom: number, panX: number): number {
  return panX + 480 + zoom * (contentX - 480);
}

function screenY(contentY: number, zoom: number, panY: number): number {
  return panY + 260 + zoom * (contentY - 260);
}

describe("map viewport transforms", () => {
  it("keeps the content below the pointer fixed while zooming", () => {
    const anchor = { x: 720, y: 140 };
    const current = { zoom: 2, panX: -40, panY: 30 };
    const contentX = 480 + (anchor.x - 480 - current.panX) / current.zoom;
    const contentY = 260 + (anchor.y - 260 - current.panY) / current.zoom;
    const next = anchoredMapZoom(current, 4, anchor.x, anchor.y);

    expect(screenX(contentX, next.zoom, next.panX)).toBeCloseTo(anchor.x);
    expect(screenY(contentY, next.zoom, next.panY)).toBeCloseTo(anchor.y);
  });

  it("resets pan when zooming back to the world view", () => {
    expect(anchoredMapZoom({ zoom: 3, panX: 80, panY: -30 }, 1, 700, 100)).toEqual({
      zoom: 1,
      panX: 0,
      panY: 0
    });
  });

  it("fits projected country bounds inside the map viewport", () => {
    const transform = fitMapBounds([[100, 100], [300, 300]]);
    expect(screenY(100, transform.zoom, transform.panY)).toBeCloseTo(24);
    expect(screenY(300, transform.zoom, transform.panY)).toBeCloseTo(496);
    expect(screenX(200, transform.zoom, transform.panX)).toBeCloseTo(480);
  });
});
