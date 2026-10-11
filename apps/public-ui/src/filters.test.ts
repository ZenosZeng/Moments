import { describe, expect, it } from "vitest";
import { filterTrips, formatPublicDate, uniquePeople } from "./filters";
import type { PublicTrip } from "./types";

const trips = [
  { id: "a", year: 2024, date: "2024-01-02", people: ["阿青"] },
  { id: "b", year: 2025, date: "2025-02-03", people: ["小林", "阿青"] }
] as PublicTrip[];

describe("public trip filters", () => {
  it("combines year and companion filters", () => {
    expect(filterTrips(trips, "2025", "阿青").map((trip) => trip.id)).toEqual(["b"]);
    expect(filterTrips(trips, "2024", "小林")).toEqual([]);
  });

  it("can additionally filter the timeline by normalized city", () => {
    const locatedTrips = [
      { ...trips[0], places: [{ city: "深圳", name: "", countryCode: "CN", countryName: "China" }] },
      { ...trips[1], places: [{ city: "广州", name: "", countryCode: "CN", countryName: "China" }] }
    ];
    expect(filterTrips(locatedTrips, "", "", " 深圳 ").map((trip) => trip.id)).toEqual(["a"]);
  });

  it("lists public nicknames once", () => {
    expect(uniquePeople(trips)).toEqual(["阿青", "小林"]);
  });

  it("formats stable ISO dates without timezone conversion", () => {
    expect(formatPublicDate("2025-02-03")).toBe("2025.02.03");
  });
});
