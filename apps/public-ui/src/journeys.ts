import { formatPublicDate, normalizedCity } from "./filters";
import type { PublicPhoto, PublicPlace, PublicTrip } from "./types";

export interface JourneySegmentDay {
  date: string;
  dateLabel: string;
  places: PublicPlace[];
  photos: PublicPhoto[];
}

export interface JourneySegment {
  id: string;
  startDate: string;
  endDate: string;
  dateLabel: string;
  title: string;
  places: PublicPlace[];
  people: string[];
  photos: PublicPhoto[];
  tripDays: number;
  tripIds: string[];
  days: JourneySegmentDay[];
}

export function normalizePublicLabels(values: string[]): string[] {
  const normalized = values.flatMap((value) =>
    value.split(/[，、,;；\s]+/u).map((item) => item.trim()).filter(Boolean)
  );
  return [...new Set(normalized)];
}

function dayNumber(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

function segmentTitle(places: PublicPlace[]): string {
  const city = places.find((place) => place.city)?.city || "";
  const names = normalizePublicLabels(places.map((place) => place.name));
  return [city, names.join("、")].filter(Boolean).join(" · ") || "照片记录";
}

export function groupJourneySegments(trips: PublicTrip[]): JourneySegment[] {
  const segments: JourneySegment[] = [];
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
      previous.dateLabel = `${formatPublicDate(previous.startDate)} 至 ${formatPublicDate(previous.endDate)}`;
      previous.tripDays += 1;
      previous.tripIds.push(trip.id);
      previous.days.push({
        date: trip.date,
        dateLabel: formatPublicDate(trip.date),
        places: [...trip.places],
        photos: [...trip.photos]
      });
      for (const place of trip.places) {
        const key = `${place.countryCode}|${place.city}|${place.name}`;
        if (!previous.places.some((item) => `${item.countryCode}|${item.city}|${item.name}` === key)) {
          previous.places.push(place);
        }
      }
      previous.people = [...new Set([...previous.people, ...trip.people])].sort((left, right) =>
        left.localeCompare(right, "zh-CN")
      );
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
      dateLabel: formatPublicDate(trip.date),
      title: segmentTitle(trip.places),
      places: [...trip.places],
      people: [...trip.people],
      photos: [...trip.photos],
      tripDays: 1,
      tripIds: [trip.id],
      days: [{
        date: trip.date,
        dateLabel: formatPublicDate(trip.date),
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
