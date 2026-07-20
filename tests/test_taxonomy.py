from __future__ import annotations

from a_stock_radar.taxonomy import ThemeMapper


def test_theme_mapping_first_match() -> None:
    mapper = ThemeMapper(
        {
            "themes": [
                {"id": "chip", "name": "芯片", "patterns": ["芯片"]},
                {"id": "other", "name": "其他", "patterns": []},
            ]
        }
    )
    assert mapper.map_name("科创芯片ETF").theme_id == "chip"
    assert mapper.map_name("未知ETF").theme_id == "other"
