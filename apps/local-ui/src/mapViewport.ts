export interface MapTransform {
  zoom: number;
  panX: number;
  panY: number;
}

export type MapBounds = [[number, number], [number, number]];

const VIEWPORT_WIDTH = 960;
const VIEWPORT_HEIGHT = 520;
const CENTER_X = VIEWPORT_WIDTH / 2;
const CENTER_Y = VIEWPORT_HEIGHT / 2;

export function anchoredMapZoom(
  current: MapTransform,
  requestedZoom: number,
  anchorX = CENTER_X,
  anchorY = CENTER_Y
): MapTransform {
  const nextZoom = Math.min(24, Math.max(1, requestedZoom));
  if (nextZoom === 1) return { zoom: 1, panX: 0, panY: 0 };
  if (nextZoom === current.zoom) return current;

  const ratio = nextZoom / current.zoom;
  return {
    zoom: nextZoom,
    panX: anchorX - CENTER_X - ratio * (anchorX - CENTER_X - current.panX),
    panY: anchorY - CENTER_Y - ratio * (anchorY - CENTER_Y - current.panY)
  };
}

export function fitMapBounds(bounds: MapBounds, padding = 24): MapTransform {
  const [[left, top], [right, bottom]] = bounds;
  const width = Math.max(1, right - left);
  const height = Math.max(1, bottom - top);
  const nextZoom = Math.min(
    24,
    Math.max(
      1,
      Math.min(
        (VIEWPORT_WIDTH - padding * 2) / width,
        (VIEWPORT_HEIGHT - padding * 2) / height
      )
    )
  );
  const boundsCenterX = (left + right) / 2;
  const boundsCenterY = (top + bottom) / 2;
  return {
    zoom: nextZoom,
    panX: (CENTER_X - boundsCenterX) * nextZoom,
    panY: (CENTER_Y - boundsCenterY) * nextZoom
  };
}
