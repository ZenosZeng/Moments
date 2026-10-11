import { describe, expect, it } from "vitest";
import { aggregateCityVisits, cityKey } from "./map-data";
import type { PublicCityCenter, PublicTrip } from "./types";

const centers: PublicCityCenter[] = [
  { key: "CN|深圳", name: "深圳", countryCode: "CN", point: [114.0683, 22.54554] },
  { key: "CN|广州", name: "广州", countryCode: "CN", point: [113.25, 23.11667] }
];

function trip(id: string, date: string, cities: string[]): PublicTrip {
  return {
    id,
    date,
    year: Number(date.slice(0, 4)),
    title: cities.join("、"),
    places: cities.map((city) => ({ city, name: "", countryCode: "CN", countryName: "China" })),
    people: [],
    photos: []
  };
}

describe("city map data", () => {
  it("builds the same key as the offline city-center importer", () => {
    expect(cityKey({ countryCode: "cn", city: " 深圳 " })).toBe("CN|深圳");
  });

  it("aggregates unique trip days and keeps the latest trip", () => {
    const visits = aggregateCityVisits(
      [trip("old", "2024-01-02", ["深圳", "深圳"]), trip("new", "2025-03-04", ["深圳", "广州"])],
      centers
    );

    expect(visits.map((visit) => [visit.name, visit.tripDays])).toEqual([
      ["广州", 1],
      ["深圳", 2]
    ]);
    expect(visits.find((visit) => visit.name === "深圳")?.trip.id).toBe("new");
  });

  it("skips locations that have no offline city center", () => {
    expect(aggregateCityVisits([trip("a", "2025-01-01", ["未知城市"])], centers)).toEqual([]);
  });
});
