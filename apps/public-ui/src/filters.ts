import type { PublicTrip } from "./types";

export function filterTrips(
  trips: PublicTrip[],
  year: string,
  city = ""
): PublicTrip[] {
  const cityKey = normalizedCity(city);
  return trips.filter(
    (trip) =>
      (!year || String(trip.year) === year) &&
      (!cityKey || trip.places.some((place) => normalizedCity(place.city) === cityKey))
  );
}

export function normalizedCity(value: string): string {
  return value.normalize("NFKC").trim().toLocaleLowerCase("zh-CN");
}

export function formatPublicDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${year}.${month}.${day}`;
}
