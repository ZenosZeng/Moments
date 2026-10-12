import { describe, expect, it } from "vitest";
import { filterTrips, formatPublicDate } from "./filters";
import type { PublicTrip } from "./types";

const trips = [
  { id: "a", year: 2024, date: "2024-01-02" },
  { id: "b", year: 2025, date: "2025-02-03" }
] as PublicTrip[];

describe("public trip filters", () => {
  it("filters trips by year", () => {
    expect(filterTrips(trips, "2025").map((trip) => trip.id)).toEqual(["b"]);
    expect(filterTrips(trips, "2023")).toEqual([]);
  });

  it("can additionally filter the timeline by normalized city", () => {
    const locatedTrips = [
      { ...trips[0], places: [{ city: "深圳", name: "", countryCode: "CN", countryName: "China" }] },
      { ...trips[1], places: [{ city: "广州", name: "", countryCode: "CN", countryName: "China" }] }
    ];
    expect(filterTrips(locatedTrips, "", " 深圳 ").map((trip) => trip.id)).toEqual(["a"]);
  });

  it("formats stable ISO dates without timezone conversion", () => {
    expect(formatPublicDate("2025-02-03")).toBe("2025.02.03");
  });
});
