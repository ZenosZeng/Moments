from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_city_centers import build_city_centers  # noqa: E402


class BuildCityCentersTest(unittest.TestCase):
    def test_builds_unique_centers_and_respects_country(self) -> None:
        manifest = {
            "trips": [
                {
                    "places": [
                        {"city": "维也纳", "countryCode": "AT"},
                        {"city": "深圳", "countryCode": "CN"},
                    ]
                },
                {"places": [{"city": "深圳", "countryCode": "CN"}]},
            ]
        }

        result = build_city_centers(manifest)

        self.assertEqual([item["key"] for item in result["cities"]], ["AT|维也纳", "CN|深圳"])
        vienna = result["cities"][0]
        self.assertAlmostEqual(vienna["point"][0], 16.37208, places=4)
        self.assertAlmostEqual(vienna["point"][1], 48.20849, places=4)

    def test_resolves_shunde_as_a_city_without_changing_its_label(self) -> None:
        manifest = {
            "trips": [
                {"places": [{"city": "顺德", "countryCode": "CN"}]},
                {"places": [{"city": "广州", "countryCode": "CN"}]},
            ]
        }

        result = build_city_centers(manifest)

        guangzhou, shunde = result["cities"]
        self.assertEqual(shunde["name"], "顺德")
        self.assertAlmostEqual(shunde["point"][0], 113.2503, places=4)
        self.assertAlmostEqual(shunde["point"][1], 22.84067, places=4)
        self.assertNotEqual(shunde["point"], guangzhou["point"])

    def test_resolves_chinese_name_when_geonames_only_has_city_suffix(self) -> None:
        manifest = {
            "trips": [
                {"places": [{"city": "扬州", "countryCode": "CN"}]},
            ]
        }

        result = build_city_centers(manifest)

        yangzhou = result["cities"][0]
        self.assertEqual(yangzhou["key"], "CN|扬州")
        self.assertAlmostEqual(yangzhou["point"][0], 119.43583, places=4)
        self.assertAlmostEqual(yangzhou["point"][1], 32.39722, places=4)

    def test_resolves_small_city_from_full_offline_dataset(self) -> None:
        manifest = {
            "trips": [
                {"places": [{"city": "井冈山", "countryCode": "CN"}]},
            ]
        }

        result = build_city_centers(manifest)

        jinggangshan = result["cities"][0]
        self.assertEqual(jinggangshan["key"], "CN|井冈山")
        self.assertEqual(jinggangshan["name"], "井冈山")
        self.assertAlmostEqual(jinggangshan["point"][0], 114.27028, places=4)
        self.assertAlmostEqual(jinggangshan["point"][1], 26.73139, places=4)

    def test_resolves_lushun_simplified_chinese_alias(self) -> None:
        manifest = {
            "trips": [
                {"places": [{"city": "旅顺", "countryCode": "CN"}]},
            ]
        }

        result = build_city_centers(manifest)

        lushun = result["cities"][0]
        self.assertEqual(lushun["key"], "CN|旅顺")
        self.assertEqual(lushun["name"], "旅顺")
        self.assertAlmostEqual(lushun["point"][0], 121.26667, places=4)
        self.assertAlmostEqual(lushun["point"][1], 38.8, places=4)

    def test_reports_all_unresolved_cities_together(self) -> None:
        manifest = {
            "trips": [
                {"places": [{"city": "不存在甲", "countryCode": "CN"}]},
                {"places": [{"city": "不存在乙", "countryCode": "JP"}]},
            ]
        }

        with self.assertRaisesRegex(ValueError, "不存在甲.*不存在乙"):
            build_city_centers(manifest)

    def test_resolves_local_chinese_alias_without_exporting_the_alias(self) -> None:
        manifest = {
            "trips": [
                {"places": [{"city": "芭提雅", "countryCode": "TH"}]},
            ]
        }

        result = build_city_centers(manifest)

        pattaya = result["cities"][0]
        self.assertEqual(pattaya["key"], "TH|芭提雅")
        self.assertEqual(pattaya["name"], "芭提雅")
        self.assertAlmostEqual(pattaya["point"][0], 100.88333, places=4)
        self.assertAlmostEqual(pattaya["point"][1], 12.93333, places=4)


if __name__ == "__main__":
    unittest.main()
