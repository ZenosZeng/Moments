from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any

import geonamescache


CITY_ALIASES = {
    "芭提雅": "Pattaya",
    "旅顺": "Lushun",
    "顺德": "Shunde",
    "维也纳": "Vienna",
}


def city_key(city: str, country_code: str) -> str:
    normalized = unicodedata.normalize("NFKC", city).strip()
    return f"{country_code.strip().upper()}|{normalized}"


def _queries(city: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", city).strip()
    query = CITY_ALIASES.get(normalized, normalized)
    queries = [query]
    if query.endswith("市") and len(query) > 1:
        queries.append(query[:-1])
    return queries


def _normalized_label(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _without_city_suffix(value: str) -> str:
    normalized = _normalized_label(value)
    return normalized[:-1] if normalized.endswith("市") else normalized


def _matches_city_label(item: dict[str, Any], query: str) -> bool:
    query_label = _normalized_label(query)
    query_without_suffix = _without_city_suffix(query)
    labels = [str(item.get("name") or "")]
    labels.extend(str(value) for value in item.get("alternatenames") or [])
    return any(
        _normalized_label(label) == query_label
        or _without_city_suffix(label) == query_without_suffix
        for label in labels
    )


def _label_variants(value: str) -> set[str]:
    normalized = _normalized_label(value)
    return {normalized, _without_city_suffix(value)} if normalized else set()


def _city_point(item: dict[str, Any], city: str) -> list[float]:
    longitude = float(item["longitude"])
    latitude = float(item["latitude"])
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"城市“{city}”的中心点超出有效范围")
    return [round(longitude, 5), round(latitude, 5)]


def _best_match(matches: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        matches,
        key=lambda item: (
            int(item.get("population") or 0),
            str(item.get("name") or ""),
        ),
    )


def resolve_city_center(
    cache: geonamescache.GeonamesCache, city: str, country_code: str
) -> list[float]:
    expected_country = country_code.strip().upper()
    matches: list[dict[str, Any]] = []
    for query in _queries(city):
        matches = [
            item
            for item in cache.search_cities(query, contains_search=False)
            if str(item.get("countrycode") or "").upper() == expected_country
        ]
        if not matches:
            matches = [
                item
                for item in cache.search_cities(query, contains_search=True)
                if str(item.get("countrycode") or "").upper() == expected_country
                and _matches_city_label(item, query)
            ]
        if matches:
            break
    if not matches:
        raise ValueError(f"无法定位城市“{city}”（{expected_country}）")

    return _city_point(_best_match(matches), city)


def resolve_all_city_centers(
    locations: dict[str, tuple[str, str]],
) -> dict[str, list[float]]:
    if not locations:
        return {}

    targets: dict[tuple[str, str], set[str]] = {}
    for key, (city, country_code) in locations.items():
        for query in _queries(city):
            for label in _label_variants(query):
                targets.setdefault((country_code, label), set()).add(key)

    target_countries = {country_code for _, country_code in locations.values()}
    matches: dict[str, list[dict[str, Any]]] = {key: [] for key in locations}
    cache = geonamescache.GeonamesCache(min_city_population=500)
    for item in cache.get_cities().values():
        country_code = str(item.get("countrycode") or "").strip().upper()
        if country_code not in target_countries:
            continue
        matched_keys: set[str] = set()
        labels = [str(item.get("name") or "")]
        labels.extend(str(value) for value in item.get("alternatenames") or [])
        for label in labels:
            for variant in _label_variants(label):
                matched_keys.update(targets.get((country_code, variant), ()))
        for key in matched_keys:
            matches[key].append(item)

    missing = [key for key in sorted(locations) if not matches[key]]
    if missing:
        details = "，".join(
            f"{locations[key][0]}（{locations[key][1]}）" for key in missing
        )
        raise ValueError(f"无法定位以下城市：{details}")

    return {
        key: _city_point(_best_match(matches[key]), locations[key][0])
        for key in locations
    }


def build_city_centers(manifest: dict[str, Any]) -> dict[str, Any]:
    locations: dict[str, tuple[str, str]] = {}
    for trip in manifest.get("trips", []):
        for place in trip.get("places", []):
            city = str(place.get("city") or "").strip()
            country_code = str(place.get("countryCode") or "").strip().upper()
            if not city or not country_code:
                continue
            key = city_key(city, country_code)
            locations.setdefault(key, (city, country_code))

    points = resolve_all_city_centers(locations)
    centers = {
        key: {
            "key": key,
            "name": city,
            "countryCode": country_code,
            "point": points[key],
        }
        for key, (city, country_code) in locations.items()
    }

    return {
        "version": 1,
        "attribution": {
            "name": "GeoNames",
            "url": "https://www.geonames.org/",
        },
        "cities": [centers[key] for key in sorted(centers)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成公开地图使用的离线城市中心点")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    city_centers = build_city_centers(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(city_centers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已生成 {len(city_centers['cities'])} 个城市中心点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
