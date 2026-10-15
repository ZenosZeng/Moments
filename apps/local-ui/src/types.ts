export interface Place {
  id?: number;
  name: string;
  city: string;
  countryCode?: string;
  countryName?: string;
}

export interface FeaturedPhoto {
  relativePath: string;
  sortOrder?: number;
}

export interface Annotation {
  date: string;
  displayDate: string;
  places: Place[];
  isPublic: boolean;
  featuredPhotos: FeaturedPhoto[];
  annotated: boolean;
}

export interface DaySummary {
  date: string;
  day: number;
  count: number;
  annotation: Annotation;
}

export interface Overview {
  selected_month: string;
  available_months: string[];
  days: DaySummary[];
  source_root: string;
  source_roots?: string[];
  summary: {
    month_photos: number;
    active_days: number;
    annotated_days: number;
    featured_days: number;
    included: number;
    missing: number;
  };
  refresh: TaskStatus;
}

export interface TaskStatus {
  state: "idle" | "running" | "complete" | "error";
  run_id: number;
  message: string;
  stage: string;
  completed: number;
  total: number;
  percent: number | null;
  elapsed_seconds: number;
  ready: boolean;
  stale: boolean;
  cache?: { reused: number; pending: number; total: number; unit: string };
  artifacts?: string[];
}

export interface StudioSettings {
  defaultCity: string;
  availableCities: string[];
}

export interface Photo {
  relative_path: string;
  thumbnail_url: string;
  preview_url: string;
  capture_time: string;
  featured: boolean;
}

export interface DayDetail {
  date: string;
  photo_count: number;
  photos: Photo[];
  photos_returned: number;
  photos_total: number;
  offset: number;
  annotation: Annotation;
}

export interface TrailPlace {
  name: string;
  city: string;
  countryCode: string;
  countryName: string;
  mapPoint: [number, number] | null;
}

export interface TrailPhoto {
  id: string;
  src: string;
  thumbnail: string;
}

export interface TrailTrip {
  id: string;
  captureDate: string;
  date: string;
  year: number;
  title: string;
  places: TrailPlace[];
  photos: TrailPhoto[];
}

export interface TrailsPreviewData {
  summary: {
    tripDays: number;
    cities: number;
    countries: number;
    featuredPhotos: number;
  };
  trips: TrailTrip[];
  warnings: string[];
}
