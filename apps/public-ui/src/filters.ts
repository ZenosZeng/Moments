import type { PublicTrip } from "./types";

export function filterTrips(
  trips: PublicTrip[],
  year: string,
  person: string,
  city = ""
): PublicTrip[] {
  const cityKey = normalizedCity(city);
  return trips.filter(
    (trip) =>
      (!year || String(trip.year) === year) &&
      (!person || trip.people.includes(person)) &&
      (!cityKey || trip.places.some((place) => normalizedCity(place.city) === cityKey))
  );
}

export function normalizedCity(value: string): string {
  return value.normalize("NFKC").trim().toLocaleLowerCase("zh-CN");
}

export function uniquePeople(trips: PublicTrip[]): string[] {
  return [...new Set(trips.flatMap((trip) => trip.people))].sort((a, b) =>
    a.localeCompare(b, "zh-CN")
  );
}

export function formatPublicDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${year}.${month}.${day}`;
}
