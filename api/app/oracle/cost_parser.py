from __future__ import annotations

import re

from app.oracle.profile import CostVector

_SYMBOL_RE = re.compile(r"\{([^}]+)\}")
_PIPS = {"W", "U", "B", "R", "G"}


def parse_mana_cost(cost: str) -> CostVector:
    """Parse a Scryfall-style mana cost like ``{2}{W}{U}`` into a CostVector.

    Handles hybrid (``{R/G}``), Phyrexian (``{B/P}``), generic, X, snow,
    colorless, and 2-brid (``{2/W}``) symbols. Hybrid symbols contribute
    fractional color demand to each side; Phyrexian contributes nothing
    to color demand (paid with life) but adds a pip to ``alt_costs``.
    """
    vector = CostVector()
    if not cost:
        return vector
    matches = _SYMBOL_RE.findall(cost)
    if not matches:
        return vector

    for sym in matches:
        sym = sym.strip().upper()
        if sym.isdigit():
            vector.generic += int(sym)
            vector.cmc += int(sym)
            continue
        if sym == "X":
            vector.pips["X"] = vector.pips.get("X", 0) + 1
            vector.alt_costs.append("x_cost")
            continue
        if sym in _PIPS:
            vector.pips[sym] = vector.pips.get(sym, 0) + 1
            vector.color_demand[sym] = vector.color_demand.get(sym, 0) + 1
            vector.cmc += 1
            vector.pip_intensity += 1.0
            continue
        if sym in {"C", "S"}:
            vector.pips[sym] = vector.pips.get(sym, 0) + 1
            vector.cmc += 1
            continue
        if "/" in sym:
            parts = [p.strip() for p in sym.split("/")]
            if len(parts) == 2 and "P" in parts:
                color = next((p for p in parts if p in _PIPS), None)
                vector.alt_costs.append(f"phyrexian:{color or 'C'}")
                if color:
                    vector.pips[color] = vector.pips.get(color, 0) + 1
                vector.cmc += 1
                vector.pip_intensity += 0.5
                continue
            if len(parts) == 2 and parts[0].isdigit():
                vector.generic += int(parts[0])
                color = parts[1]
                if color in _PIPS:
                    vector.color_demand[color] = vector.color_demand.get(color, 0) + 0.5
                    vector.pips[color] = vector.pips.get(color, 0) + 1
                vector.cmc += int(parts[0])
                vector.pip_intensity += 0.5
                continue
            if all(p in _PIPS for p in parts):
                for p in parts:
                    vector.color_demand[p] = vector.color_demand.get(p, 0) + 1.0 / len(parts)
                    vector.pips[p] = vector.pips.get(p, 0) + 1
                vector.cmc += 1
                vector.pip_intensity += 0.7
                continue
        vector.alt_costs.append(f"unknown:{sym}")
    return vector


def cost_pip_count(vector: CostVector, color: str) -> int:
    return int(vector.pips.get(color.upper(), 0))


def cost_color_demand(vector: CostVector) -> dict[str, float]:
    return dict(vector.color_demand)


def cost_is_double_pip(vector: CostVector) -> bool:
    return any(v >= 2 for v in vector.color_demand.values())
