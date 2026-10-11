from __future__ import annotations

import pytest

from pic_timeline.city_country import country_from_code, infer_city, infer_country


@pytest.mark.parametrize(
    ("city", "country_code"),
    [
        ("深圳", "CN"),
        ("顺德", "CN"),
        ("成都市", "CN"),
        ("维也纳", "AT"),
        ("芭提雅", "TH"),
        ("扬州", "CN"),
        ("滨州", "CN"),
        ("东营", "CN"),
        ("巴黎", "FR"),
        ("Paris", "FR"),
    ],
)
def test_infer_country_from_city_aliases(city: str, country_code: str) -> None:
    assert infer_country(city).code == country_code


def test_infer_country_rejects_unknown_city() -> None:
    with pytest.raises(ValueError, match="无法根据城市"):
        infer_country("绝不存在的测试城市")


def test_infer_city_returns_offline_city_center() -> None:
    shenzhen = infer_city("深圳")
    assert shenzhen.code == "CN"
    assert shenzhen.longitude == pytest.approx(114.0683)
    assert shenzhen.latitude == pytest.approx(22.54554)


def test_shunde_uses_its_own_city_center() -> None:
    shunde = infer_city("顺德")
    guangzhou = infer_city("广州")
    assert shunde.code == "CN"
    assert shunde.longitude == pytest.approx(113.2503)
    assert shunde.latitude == pytest.approx(22.84067)
    assert (shunde.longitude, shunde.latitude) != (
        guangzhou.longitude,
        guangzhou.latitude,
    )


def test_country_from_code_returns_canonical_country() -> None:
    assert country_from_code("cn").name == "China"
    with pytest.raises(ValueError, match="国家代码"):
        country_from_code("ZZ")
