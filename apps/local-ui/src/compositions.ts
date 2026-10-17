export interface CompositionDate {
  captureDate: string;
  date: string;
  cities: string[];
  places: string[];
  count?: number;
}

export interface CompositionPhoto {
  id: string;
  captureDate: string;
  relativePath: string;
  src: string;
  thumbnail: string;
  filter?: { version: number; preset: string; strength: number };
  preset: string;
  strength: number;
}

export interface CompositionGroup {
  schemaVersion: number;
  id: string;
  etag: string;
  directory: string;
  title: string;
  location: string;
  captionTitle: string;
  caption: string;
  publishDate?: string;
  autoPublishDate?: boolean;
  createdAt?: string;
  sourceDates: string[];
  days: CompositionDate[];
  cities: string[];
  time: { start: string; end: string; dates: string[] };
  autoFill?: { time: boolean; cities: boolean };
  updatedAt: string;
  photos: CompositionPhoto[];
}

export interface FilterPreset { id: string; name: string }

export function localDate(value = new Date()): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

export function nextPublishDate(start: string, occupied: string[]): string {
  const dates = new Set(occupied);
  const candidate = new Date(`${start}T00:00:00Z`);
  while (dates.has(candidate.toISOString().slice(0, 10))) candidate.setUTCDate(candidate.getUTCDate() + 1);
  return candidate.toISOString().slice(0, 10);
}

export function splitLocations(values: string[]): string[] {
  return [...new Set(values.flatMap(value => value.split(/[、，,;；\r\n]+/)).map(value => value.trim()).filter(Boolean))];
}

export function editPhoto(photo: CompositionPhoto): CompositionPhoto {
  return { ...photo, preset: photo.filter?.preset ?? photo.preset ?? "original", strength: photo.filter?.strength ?? photo.strength ?? 100 };
}

export function imageUrl(photo: CompositionPhoto, size = "thumb", preset = photo.preset, strength = photo.strength): string {
  const [path, query = ""] = photo.src.split("?");
  const parameters = new URLSearchParams(query);
  parameters.set("size", size);
  parameters.set("preset", preset || "original");
  parameters.set("strength", String(strength ?? 100));
  return `${path}?${parameters}`;
}

export function dateRange(days: CompositionDate[]): string {
  const dates = [...new Set(days.map(day => day.date))].sort();
  return dates.length < 2 ? dates[0] || "—" : `${dates[0]} 至 ${dates[dates.length - 1]}`;
}

export function movePhoto(photos: CompositionPhoto[], index: number, target: number): CompositionPhoto[] {
  const result = [...photos];
  if (index >= 0 && target >= 0 && index < result.length && target < result.length) {
    const [photo] = result.splice(index, 1);
    result.splice(target, 0, photo);
  }
  return result;
}
