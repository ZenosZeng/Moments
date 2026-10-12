import type { TrailPhoto, TrailPlace, TrailTrip } from "./types";

const TRAIL_CITY_PALETTE = [
  "#e05a3f",
  "#16857b",
  "#2f6f9f",
  "#bd7b16",
  "#8b5fa8",
  "#4f7f45",
  "#c64f70",
  "#5e6fbb"
];

export interface CityVisit {
  key: string;
  name: string;
  point: [number, number];
  tripDays: number;
  trip: TrailTrip;
}

export interface TrailSegment {
  id: string;
  startDate: string;
  endDate: string;
  dateLabel: string;
  title: string;
  places: TrailPlace[];
  photos: TrailPhoto[];
  tripDays: number;
  tripIds: string[];
  days: TrailSegmentDay[];
}

export interface TrailSegmentDay {
  captureDate: string;
  date: string;
  dateLabel: string;
  places: TrailPlace[];
  photos: TrailPhoto[];
}

export function filterTrailTrips(
  trips: TrailTrip[],
  year: string,
  city = ""
): TrailTrip[] {
  const cityKey = normalizedCity(city);
  return trips.filter(
    (trip) =>
      (!year || String(trip.year) === year) &&
      (!cityKey || trip.places.some((place) => normalizedCity(place.city) === cityKey))
  );
}

export function trailCityKey(place: TrailPlace): string {
  return `${place.countryCode}|${place.city.normalize("NFKC").trim()}`;
}

export function aggregateCityVisits(trips: TrailTrip[]): CityVisit[] {
  const visits = new Map<string, CityVisit>();
  for (const trip of trips) {
    const seen = new Set<string>();
    for (const place of trip.places) {
      if (!place.city || !place.mapPoint) continue;
      const key = trailCityKey(place);
      if (seen.has(key)) continue;
      seen.add(key);
      const existing = visits.get(key);
      if (existing) {
        existing.tripDays += 1;
        if (trip.date > existing.trip.date) existing.trip = trip;
      } else {
        visits.set(key, {
          key,
          name: place.city,
          point: place.mapPoint,
          tripDays: 1,
          trip
        });
      }
    }
  }
  return [...visits.values()].sort((left, right) =>
    left.name.localeCompare(right.name, "zh-CN")
  );
}

export function formatTrailDate(value: string): string {
  return value.split("-").join(".");
}

export function normalizeTrailLabels(values: string[]): string[] {
  const normalized = values.flatMap((value) =>
    value.split(/[，,、;；\s]+/u).map((item) => item.trim()).filter(Boolean)
  );
  return [...new Set(normalized)];
}

function dayNumber(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

export function normalizedCity(value: string): string {
  return value.normalize("NFKC").trim().toLocaleLowerCase("zh-CN");
}

export function trailCityColor(city: string): string {
  const hash = Array.from(normalizedCity(city)).reduce(
    (value, character) => ((value * 31) + (character.codePointAt(0) || 0)) >>> 0,
    0
  );
  return TRAIL_CITY_PALETTE[hash % TRAIL_CITY_PALETTE.length];
}

function segmentTitle(places: TrailPlace[]): string {
  const city = places.find((place) => place.city)?.city || "";
  const names = [...new Set(places.map((place) => place.name).filter(Boolean))];
  return [city, names.join("、")].filter(Boolean).join(" · ") || "照片记录";
}

export function groupTrailSegments(trips: TrailTrip[]): TrailSegment[] {
  const segments: TrailSegment[] = [];
  const sorted = [...trips].sort((left, right) => left.date.localeCompare(right.date));

  for (const trip of sorted) {
    const city = trip.places.find((place) => place.city)?.city.trim() || "";
    const previous = segments[segments.length - 1];
    const previousCity = previous?.places.find((place) => place.city)?.city || "";
    const canMerge = Boolean(
      previous &&
      city &&
      normalizedCity(city) === normalizedCity(previousCity) &&
      dayNumber(trip.date) - dayNumber(previous.endDate) === 1
    );

    if (canMerge) {
      previous.endDate = trip.date;
      previous.dateLabel = `${formatTrailDate(previous.startDate)} 至 ${formatTrailDate(previous.endDate)}`;
      previous.tripDays += 1;
      previous.tripIds.push(trip.id);
      previous.days.push({
        captureDate: trip.captureDate,
        date: trip.date,
        dateLabel: formatTrailDate(trip.date),
        places: [...trip.places],
        photos: [...trip.photos]
      });
      for (const place of trip.places) {
        const key = `${place.countryCode}|${place.city}|${place.name}`;
        if (!previous.places.some((item) => `${item.countryCode}|${item.city}|${item.name}` === key)) {
          previous.places.push(place);
        }
      }
      previous.photos.push(...trip.photos.filter(
        (photo) => !previous.photos.some((item) => item.id === photo.id)
      ));
      previous.title = segmentTitle(previous.places);
      previous.id = `segment-${previous.startDate}-${previous.endDate}-${city}`;
      continue;
    }

    segments.push({
      id: `segment-${trip.date}-${trip.date}-${city}`,
      startDate: trip.date,
      endDate: trip.date,
      dateLabel: formatTrailDate(trip.date),
      title: segmentTitle(trip.places),
      places: [...trip.places],
      photos: [...trip.photos],
      tripDays: 1,
      tripIds: [trip.id],
      days: [{
        captureDate: trip.captureDate,
        date: trip.date,
        dateLabel: formatTrailDate(trip.date),
        places: [...trip.places],
        photos: [...trip.photos]
      }]
    });
  }

  return segments.reverse().map((segment) => ({
    ...segment,
    days: [...segment.days].reverse()
  }));
}
