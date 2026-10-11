from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import geonamescache


_CITY_ALIASES = {
    "顺德": "Shunde",
    "维也纳": "Vienna",
    "芭提雅": "Pattaya",
    "扬州": "Yangzhou",
    "滨州": "Binzhou",
    "东营": "Dongying",
}


@dataclass(frozen=True)
class CountryMatch:
    code: str
    name: str


@dataclass(frozen=True)
class CityMatch:
    code: str
    name: str
    latitude: float
    longitude: float


@lru_cache(maxsize=1)
def _cache() -> geonamescache.GeonamesCache:
    return geonamescache.GeonamesCache()


def _queries(city: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", city).strip()
    query = _CITY_ALIASES.get(normalized, normalized)
    queries = [query]
    if query.endswith("市") and len(query) > 1:
        queries.append(query[:-1])
    return queries


@lru_cache(maxsize=512)
def infer_city(city: str) -> CityMatch:
    queries = _queries(city)
    if not queries or not queries[0]:
        raise ValueError("城市为空，无法推导国家")

    cache = _cache()
    matches: list[dict[str, object]] = []
    for query in queries:
        matches.extend(cache.search_cities(query, contains_search=False))
        if matches:
            break
    if not matches:
        raise ValueError(f"无法根据城市“{queries[0]}”推导国家")

    city_match = max(
        matches,
        key=lambda item: (
            int(item.get("population") or 0),
            str(item.get("name") or ""),
            str(item.get("countrycode") or ""),
        ),
    )
    country_code = str(city_match.get("countrycode") or "").upper()
    country = cache.get_countries().get(country_code)
    if not country_code or country is None:
        raise ValueError(f"城市“{queries[0]}”缺少可用的国家信息")
    try:
        latitude = float(city_match["latitude"])
        longitude = float(city_match["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"城市“{queries[0]}”缺少可用的中心坐标") from exc
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(f"城市“{queries[0]}”的中心坐标超出有效范围")
    return CityMatch(
        code=country_code,
        name=str(country["name"]),
        latitude=latitude,
        longitude=longitude,
    )


@lru_cache(maxsize=512)
def infer_country(city: str) -> CountryMatch:
    match = infer_city(city)
    return CountryMatch(code=match.code, name=match.name)


@lru_cache(maxsize=256)
def country_from_code(code: str) -> CountryMatch:
    normalized = unicodedata.normalize("NFKC", code).strip().upper()
    country = _cache().get_countries().get(normalized)
    if country is None:
        raise ValueError(f"国家代码“{normalized}”无效")
    return CountryMatch(code=normalized, name=str(country["name"]))
