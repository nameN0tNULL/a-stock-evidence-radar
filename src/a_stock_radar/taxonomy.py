from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    theme_id: str
    theme_name: str


class ThemeMapper:
    def __init__(self, config: dict):
        self.rules: list[tuple[str, str, list[re.Pattern[str]]]] = []
        for item in config.get("themes", []):
            patterns = [re.compile(re.escape(str(p)), re.IGNORECASE) for p in item.get("patterns", [])]
            self.rules.append((item["id"], item["name"], patterns))

    def map_name(self, name: str) -> Theme:
        text = str(name or "")
        fallback = Theme("other", "其他ETF")
        for theme_id, theme_name, patterns in self.rules:
            if theme_id == "other":
                fallback = Theme(theme_id, theme_name)
                continue
            if any(pattern.search(text) for pattern in patterns):
                return Theme(theme_id, theme_name)
        return fallback
