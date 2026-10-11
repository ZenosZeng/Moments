import type { FeaturedPhoto, Photo } from "./types";

export function monthLabel(value: string): string {
  const [year, month] = value.split("-");
  return `${year} 年 ${Number(month)} 月`;
}

export function weekendLabel(value: string): "周六" | "周日" | "" {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return "";
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  if (weekday === 6) return "周六";
  if (weekday === 0) return "周日";
  return "";
}

export function initialAnnotationCity(annotated: boolean, defaultCity: string): string {
  return annotated ? "" : defaultCity.trim();
}

export function updateFeatured(
  current: FeaturedPhoto[],
  photo: Pick<Photo, "relative_path">
): FeaturedPhoto[] {
  const exists = current.some((item) => item.relativePath === photo.relative_path);
  if (exists) {
    return current.filter((item) => item.relativePath !== photo.relative_path);
  }
  return [...current, { relativePath: photo.relative_path }];
}

export function compactPath(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/");
  return parts.length > 2 ? `.../${parts.slice(-2).join("/")}` : path;
}
