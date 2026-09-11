"""
Serves the per-village Jharkhand soil profiles derived from the Soil Health Card
"Soil Nutrient Analysis" export (see scripts/build_soil_profiles.py).

Lets the app fill in N / P / K / pH from real measured soil once a farmer picks
their district, block and village, instead of asking them to type numbers they
would have to get from a lab report.
"""

import json
from typing import Any, Optional

from core.config import SOIL_PROFILES_PATH

# district -> block -> [village profile, ...]
_profiles: dict[str, dict[str, list[dict[str, Any]]]] = {}
# village_code -> profile (with district/block attached) for O(1) lookup
_by_code: dict[int, dict[str, Any]] = {}


def load_soil_profiles() -> None:
    """Call once on FastAPI startup (see main.py lifespan)."""
    global _profiles, _by_code

    if not SOIL_PROFILES_PATH.exists():
        print(f"WARNING: soil profiles not found at {SOIL_PROFILES_PATH}. "
              f"Run `python scripts/build_soil_profiles.py` to generate them.")
        return

    with open(SOIL_PROFILES_PATH) as f:
        _profiles = json.load(f)

    _by_code = {}
    for district, blocks in _profiles.items():
        for block, villages in blocks.items():
            for village in villages:
                _by_code[int(village["village_code"])] = {
                    **village,
                    "district_name": district,
                    "block_name": block,
                }

    print(f"Loaded soil profiles for {len(_by_code):,} villages "
          f"across {len(_profiles)} districts from {SOIL_PROFILES_PATH.name}")


def is_loaded() -> bool:
    return bool(_by_code)


def list_districts() -> list[str]:
    return sorted(_profiles)


def list_blocks(district: str) -> Optional[list[str]]:
    blocks = _profiles.get(district)
    if blocks is None:
        return None
    return sorted(blocks)


def list_villages(district: str, block: str) -> Optional[list[dict[str, Any]]]:
    blocks = _profiles.get(district)
    if blocks is None:
        return None
    villages = blocks.get(block)
    if villages is None:
        return None
    return [
        {"village_name": v["village_name"], "village_code": v["village_code"]}
        for v in villages
    ]


def get_profile(village_code: int) -> Optional[dict[str, Any]]:
    return _by_code.get(int(village_code))


def summary() -> dict[str, Any]:
    return {
        "districts": len(_profiles),
        "blocks": sum(len(b) for b in _profiles.values()),
        "villages": len(_by_code),
    }
