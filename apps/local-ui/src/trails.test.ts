import { describe, expect, it } from "vitest";
import {
  aggregateCityVisits,
  filterTrailTrips,
  groupTrailSegments,
  normalizeTrailLabels
} from "./trails";
import type { TrailTrip } from "./types";

function trip(id: string, date: string, city: string): TrailTrip {
  return {
    id,
    captureDate: date,
    date,
    year: Number(date.slice(0, 4)),
    title: city,
    places: [{
      city,
      name: "",
      countryCode: "CN",
      countryName: "China",
      mapPoint: city === "深圳" ? [114.0683, 22.54554] : [113.25, 23.11667]
    }],
    photos: []
  };
}

describe("local trails preview data", () => {
  const trips = [
    trip("old", "2024-01-01", "深圳"),
    trip("new", "2025-02-02", "深圳"),
    trip("other", "2025-03-03", "广州")
  ];

  it("filters trips by year", () => {
    expect(filterTrailTrips(trips, "2025").map((item) => item.id)).toEqual(["new", "other"]);
  });

  it("filters the timeline by city without affecting other filters", () => {
    expect(filterTrailTrips(trips, "2025", " 深圳 ").map((item) => item.id)).toEqual(["new"]);
    expect(filterTrailTrips(trips, "2025", "广州").map((item) => item.id)).toEqual(["other"]);
  });

  it("aggregates city days and keeps the latest trip", () => {
    const cities = aggregateCityVisits(trips);
    expect(cities.map((city) => [city.name, city.tripDays])).toEqual([
      ["广州", 1],
      ["深圳", 2]
    ]);
    expect(cities.find((city) => city.name === "深圳")?.trip.id).toBe("new");
  });

  it("normalizes preview separators to individual labels", () => {
    expect(normalizeTrailLabels(["西湖、灵隐寺", "河坊街 夜市", "西湖"])).toEqual([
      "西湖",
      "灵隐寺",
      "河坊街",
      "夜市"
    ]);
  });

  it("merges adjacent dates in the same city into a journey segment", () => {
    const segments = groupTrailSegments([
      trip("a", "2025-02-01", "深圳"),
      trip("b", "2025-02-02", "深圳"),
      trip("c", "2025-02-03", "广州")
    ]);

    expect(segments.map((segment) => [segment.dateLabel, segment.title])).toEqual([
      ["2025.02.03", "广州"],
      ["2025.02.01 至 2025.02.02", "深圳"]
    ]);
    expect(segments[1]).not.toHaveProperty("people");
    expect(segments[1].tripDays).toBe(2);
    expect(segments[1].tripIds).toEqual(["a", "b"]);
    expect(segments[1].days.map((day) => day.date)).toEqual(["2025-02-02", "2025-02-01"]);
    expect(segments[1].days.map((day) => day.captureDate)).toEqual(["2025-02-02", "2025-02-01"]);
  });
});
