import type { PublicCityCenter, PublicPlace, PublicTrip } from "./types";

export interface CityVisit extends PublicCityCenter {
  tripDays: number;
  trip: PublicTrip;
}

export function cityKey(place: Pick<PublicPlace, "city" | "countryCode">): string {
  return `${place.countryCode.trim().toUpperCase()}|${place.city.normalize("NFKC").trim()}`;
}

export function aggregateCityVisits(
  trips: PublicTrip[],
  centers: PublicCityCenter[]
): CityVisit[] {
  const centersByKey = new Map(centers.map((center) => [center.key, center]));
  const visitsByKey = new Map<string, CityVisit>();

  for (const trip of trips) {
    const citiesSeenOnTrip = new Set<string>();
    for (const place of trip.places) {
      const key = cityKey(place);
      const center = centersByKey.get(key);
      if (!center || citiesSeenOnTrip.has(key)) continue;
      citiesSeenOnTrip.add(key);

      const existing = visitsByKey.get(key);
      if (existing) {
        existing.tripDays += 1;
        if (trip.date > existing.trip.date) existing.trip = trip;
      } else {
        visitsByKey.set(key, { ...center, tripDays: 1, trip });
      }
    }
  }

  return [...visitsByKey.values()].sort((left, right) =>
    left.name.localeCompare(right.name, "zh-CN")
  );
}
