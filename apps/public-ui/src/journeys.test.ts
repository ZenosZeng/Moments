import { describe, expect, it } from "vitest";
import { groupJourneySegments, normalizePublicLabels } from "./journeys";
import type { PublicTrip } from "./types";

function trip(id: string, date: string, city: string, people: string[]): PublicTrip {
  return {
    id,
    date,
    year: Number(date.slice(0, 4)),
    title: city,
    places: [{ city, name: "", countryCode: "CN", countryName: "China" }],
    people,
    photos: []
  };
}

describe("public journey timeline", () => {
  it("splits combined location labels and removes duplicates", () => {
    expect(normalizePublicLabels(["西湖、灵隐寺", "河坊街 夜市", "西湖"])).toEqual([
      "西湖",
      "灵隐寺",
      "河坊街",
      "夜市"
    ]);
  });

  it("merges adjacent dates in the same city and keeps days for galleries", () => {
    const segments = groupJourneySegments([
      trip("a", "2025-02-01", "深圳", ["阿青"]),
      trip("b", "2025-02-02", "深圳", ["小林"]),
      trip("c", "2025-02-03", "广州", [])
    ]);

    expect(segments.map((segment) => [segment.dateLabel, segment.title])).toEqual([
      ["2025.02.03", "广州"],
      ["2025.02.01 至 2025.02.02", "深圳"]
    ]);
    expect(segments[1].people).toEqual(["阿青", "小林"]);
    expect(segments[1].tripIds).toEqual(["a", "b"]);
    expect(segments[1].days.map((day) => day.date)).toEqual(["2025-02-02", "2025-02-01"]);
  });

  it("does not merge separated dates or records without a city", () => {
    const segments = groupJourneySegments([
      trip("a", "2025-02-01", "深圳", []),
      trip("b", "2025-02-03", "深圳", []),
      trip("c", "2025-02-04", "", [])
    ]);
    expect(segments).toHaveLength(3);
  });
});
