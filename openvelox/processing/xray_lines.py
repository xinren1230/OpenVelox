"""Compact X-ray emission line table (keV) for TEM-EDS identification."""

from __future__ import annotations

# (Z, symbol, name, Ka, Kb, La, Lb, Ma) — None if not typically used.
_ROWS: list[tuple[int, str, str, float | None, float | None, float | None, float | None, float | None]] = [
    (1, "H", "Hydrogen", None, None, None, None, None),
    (2, "He", "Helium", None, None, None, None, None),
    (3, "Li", "Lithium", 0.054, None, None, None, None),
    (4, "Be", "Beryllium", 0.109, None, None, None, None),
    (5, "B", "Boron", 0.183, None, None, None, None),
    (6, "C", "Carbon", 0.277, None, None, None, None),
    (7, "N", "Nitrogen", 0.392, None, None, None, None),
    (8, "O", "Oxygen", 0.525, None, None, None, None),
    (9, "F", "Fluorine", 0.677, None, None, None, None),
    (10, "Ne", "Neon", 0.848, None, None, None, None),
    (11, "Na", "Sodium", 1.041, None, None, None, None),
    (12, "Mg", "Magnesium", 1.254, None, None, None, None),
    (13, "Al", "Aluminium", 1.487, None, None, None, None),
    (14, "Si", "Silicon", 1.740, None, None, None, None),
    (15, "P", "Phosphorus", 2.013, None, None, None, None),
    (16, "S", "Sulfur", 2.307, None, None, None, None),
    (17, "Cl", "Chlorine", 2.622, None, None, None, None),
    (18, "Ar", "Argon", 2.957, None, None, None, None),
    (19, "K", "Potassium", 3.313, 3.589, None, None, None),
    (20, "Ca", "Calcium", 3.691, 4.012, 0.341, None, None),
    (21, "Sc", "Scandium", 4.090, 4.460, 0.395, None, None),
    (22, "Ti", "Titanium", 4.510, 4.931, 0.452, None, None),
    (23, "V", "Vanadium", 4.952, 5.427, 0.511, None, None),
    (24, "Cr", "Chromium", 5.414, 5.946, 0.573, None, None),
    (25, "Mn", "Manganese", 5.898, 6.490, 0.637, None, None),
    (26, "Fe", "Iron", 6.403, 7.057, 0.705, None, None),
    (27, "Co", "Cobalt", 6.930, 7.649, 0.776, None, None),
    (28, "Ni", "Nickel", 7.477, 8.264, 0.851, None, None),
    (29, "Cu", "Copper", 8.047, 8.904, 0.930, None, None),
    (30, "Zn", "Zinc", 8.638, 9.571, 1.012, None, None),
    (31, "Ga", "Gallium", 9.251, 10.263, 1.098, None, None),
    (32, "Ge", "Germanium", 9.886, 10.981, 1.188, None, None),
    (33, "As", "Arsenic", 10.543, 11.725, 1.282, None, None),
    (34, "Se", "Selenium", 11.222, 12.495, 1.379, None, None),
    (35, "Br", "Bromine", 11.923, 13.290, 1.480, None, None),
    (36, "Kr", "Krypton", 12.649, 14.112, 1.586, None, None),
    (37, "Rb", "Rubidium", 13.394, 14.960, 1.694, None, None),
    (38, "Sr", "Strontium", 14.164, 15.835, 1.806, None, None),
    (39, "Y", "Yttrium", 14.957, 16.737, 1.922, None, None),
    (40, "Zr", "Zirconium", 15.774, 17.667, 2.042, None, None),
    (41, "Nb", "Niobium", 16.614, 18.621, 2.166, None, None),
    (42, "Mo", "Molybdenum", 17.478, 19.607, 2.293, 2.395, None),
    (44, "Ru", "Ruthenium", 19.278, 21.655, 2.558, 2.683, None),
    (45, "Rh", "Rhodium", 20.214, 22.721, 2.696, 2.834, None),
    (46, "Pd", "Palladium", 21.175, 23.816, 2.838, 2.990, None),
    (47, "Ag", "Silver", 22.162, 24.942, 2.984, 3.150, None),
    (48, "Cd", "Cadmium", 23.172, 26.093, 3.133, 3.316, None),
    (49, "In", "Indium", 24.207, 27.274, 3.286, 3.487, None),
    (50, "Sn", "Tin", 25.270, 28.483, 3.443, 3.662, None),
    (51, "Sb", "Antimony", 26.357, 29.723, 3.604, 3.843, None),
    (52, "Te", "Tellurium", 27.471, 30.993, 3.769, 4.029, None),
    (53, "I", "Iodine", 28.610, 32.292, 3.937, 4.220, None),
    (56, "Ba", "Barium", 32.188, 36.369, 4.465, 4.827, None),
    (57, "La", "Lanthanum", 33.440, 37.797, 4.650, 5.041, 0.833),
    (58, "Ce", "Cerium", 34.717, 39.253, 4.839, 5.261, 0.883),
    (60, "Nd", "Neodymium", 37.355, 42.264, 5.229, 5.721, 0.978),
    (62, "Sm", "Samarium", 40.124, 45.400, 5.635, 6.205, 1.081),
    (64, "Gd", "Gadolinium", 42.983, 48.718, 6.053, 6.708, 1.185),
    (66, "Dy", "Dysprosium", 45.985, 52.178, 6.495, 7.247, 1.293),
    (68, "Er", "Erbium", 49.099, 55.689, 6.947, 7.810, 1.406),
    (70, "Yb", "Ytterbium", 52.360, 59.352, 7.414, 8.401, 1.521),
    (72, "Hf", "Hafnium", 55.786, 63.209, 7.898, 9.021, 1.644),
    (73, "Ta", "Tantalum", 57.524, 65.210, 8.145, 9.341, 1.709),
    (74, "W", "Tungsten", 59.310, 67.233, 8.396, 9.670, 1.774),
    (75, "Re", "Rhenium", 61.140, 69.309, 8.651, 10.008, 1.842),
    (76, "Os", "Osmium", 63.000, 71.404, 8.910, 10.354, 1.910),
    (77, "Ir", "Iridium", 64.886, 73.549, 9.174, 10.706, 1.979),
    (78, "Pt", "Platinum", 66.820, 75.736, 9.441, 11.069, 2.050),
    (79, "Au", "Gold", 68.794, 77.968, 9.711, 11.439, 2.123),
    (80, "Hg", "Mercury", 70.818, 80.253, 9.987, 11.823, 2.195),
    (82, "Pb", "Lead", 74.957, 84.922, 10.549, 12.611, 2.345),
    (83, "Bi", "Bismuth", 77.107, 87.343, 10.836, 13.021, 2.419),
    (90, "Th", "Thorium", 93.334, 105.592, 12.966, 16.199, 2.996),
    (92, "U", "Uranium", 98.428, 111.289, 13.613, 17.218, 3.171),
]

# Fill remaining Z 1-98 with Moseley estimates where the table is sparse.
_BY_Z: dict[int, dict] = {}
_BY_SYM: dict[str, dict] = {}


def _moseley_ka(z: int) -> float:
    return 0.0102 * (z - 1) ** 2


def _element_names() -> dict[int, tuple[str, str]]:
    return {
        43: ("Tc", "Technetium"),
        54: ("Xe", "Xenon"),
        55: ("Cs", "Caesium"),
        59: ("Pr", "Praseodymium"),
        61: ("Pm", "Promethium"),
        63: ("Eu", "Europium"),
        65: ("Tb", "Terbium"),
        67: ("Ho", "Holmium"),
        69: ("Tm", "Thulium"),
        71: ("Lu", "Lutetium"),
        81: ("Tl", "Thallium"),
        84: ("Po", "Polonium"),
        85: ("At", "Astatine"),
        86: ("Rn", "Radon"),
        87: ("Fr", "Francium"),
        88: ("Ra", "Radium"),
        89: ("Ac", "Actinium"),
        91: ("Pa", "Protactinium"),
    }


def _init() -> None:
    extras = _element_names()
    for z, sym, name, ka, kb, la, lb, ma in _ROWS:
        rec = {"Z": z, "symbol": sym, "name": name, "Ka": ka, "Kb": kb, "La": la, "Lb": lb, "Ma": ma}
        _BY_Z[z] = rec
        _BY_SYM[sym] = rec
    for z in range(1, 99):
        if z in _BY_Z:
            continue
        sym, name = extras.get(z, (f"Z{z}", f"Z={z}"))
        rec = {
            "Z": z,
            "symbol": sym,
            "name": name,
            "Ka": _moseley_ka(z) if z < 50 else None,
            "Kb": None,
            "La": 0.0136 * (z - 7.4) ** 2 / 4 if z >= 30 else None,
            "Lb": None,
            "Ma": 0.0035 * (z - 22) ** 2 if z >= 57 else None,
        }
        _BY_Z[z] = rec
        _BY_SYM[sym] = rec


_init()


PERIODIC_ORDER: list[str | None] = [
    "H", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, "He",
    "Li", "Be", None, None, None, None, None, None, None, None, None, None, "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", None, None, None, None, None, None, None, None, None, None, "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
    None, None, None, "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", None,
    None, None, None, "Th", "Pa", "U", None, None, None, None, None, None, None, None, None, None, None, None,
]


GROUPS = {
    "alkali": {"Li", "Na", "K", "Rb", "Cs", "Fr"},
    "alkaline": {"Be", "Mg", "Ca", "Sr", "Ba", "Ra"},
    "transition": {
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
        "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    },
    "lanthanide": {"La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"},
    "actinide": {"Ac", "Th", "Pa", "U"},
    "nonmetal": {"H", "C", "N", "O", "P", "S", "Se"},
    "halogen": {"F", "Cl", "Br", "I", "At"},
    "noble": {"He", "Ne", "Ar", "Kr", "Xe", "Rn"},
    "metalloid": {"B", "Si", "Ge", "As", "Sb", "Te"},
}


def element(symbol: str) -> dict:
    return _BY_SYM[symbol]


def all_elements() -> list[dict]:
    return [_BY_Z[z] for z in sorted(_BY_Z)]


def lines_for(symbol: str) -> list[tuple[str, float]]:
    rec = element(symbol)
    out = []
    for key in ("Ka", "Kb", "La", "Lb", "Ma"):
        val = rec.get(key)
        if val:
            out.append((f"{symbol} {key[0]}{chr(945) if key[1] == 'a' else chr(946)}", float(val)))
            # Keep ASCII names too — UI uses Ka/La/Ma
            out[-1] = (f"{symbol} {key}", float(val))
    return out


def preferred_line(symbol: str, emax: float = 20.0) -> tuple[str, float] | None:
    rec = element(symbol)
    for key in ("Ka", "La", "Ma", "Kb", "Lb"):
        val = rec.get(key)
        if val and 0.1 < float(val) < emax:
            return f"{symbol} {key}", float(val)
    return None


def match_peak(energy_kev: float, tolerance: float = 0.08) -> list[tuple[str, str, float, float]]:
    """Return (symbol, line, energy, delta) candidates near a peak."""
    hits = []
    for rec in _BY_Z.values():
        for key in ("Ka", "Kb", "La", "Lb", "Ma"):
            val = rec.get(key)
            if not val:
                continue
            delta = abs(float(val) - energy_kev)
            if delta <= tolerance:
                hits.append((rec["symbol"], key, float(val), delta))
    hits.sort(key=lambda item: item[3])
    return hits


# Approximate Cliff-Lorimer k-factors versus Si at 200 kV (thin-film, order-of-magnitude).
K_FACTORS_VS_SI = {
    "C": 3.6,
    "N": 3.1,
    "O": 2.4,
    "F": 1.9,
    "Na": 1.15,
    "Mg": 1.02,
    "Al": 1.05,
    "Si": 1.00,
    "P": 1.08,
    "S": 1.10,
    "Cl": 1.12,
    "K": 1.15,
    "Ca": 1.18,
    "Ti": 1.14,
    "V": 1.13,
    "Cr": 1.20,
    "Mn": 1.22,
    "Fe": 1.25,
    "Co": 1.28,
    "Ni": 1.32,
    "Cu": 1.40,
    "Zn": 1.45,
    "Ga": 1.50,
    "Ge": 1.55,
    "Sr": 1.70,
    "Y": 1.65,
    "Zr": 1.75,
    "Mo": 1.80,
    "Ag": 2.10,
    "Sn": 2.20,
    "Ba": 2.40,
    "W": 2.60,
    "Pt": 2.80,
    "Au": 2.70,
    "Pb": 3.00,
    "U": 3.40,
}

# Standard atomic weights for converting Cliff–Lorimer wt.% → at.%.
ATOMIC_MASS = {
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "Na": 22.990,
    "Mg": 24.305,
    "Al": 26.982,
    "Si": 28.085,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "K": 39.098,
    "Ca": 40.078,
    "Ti": 47.867,
    "V": 50.942,
    "Cr": 51.996,
    "Mn": 54.938,
    "Fe": 55.845,
    "Co": 58.933,
    "Ni": 58.693,
    "Cu": 63.546,
    "Zn": 65.38,
    "Ga": 69.723,
    "Ge": 72.630,
    "Sr": 87.62,
    "Y": 88.906,
    "Zr": 91.224,
    "Mo": 95.95,
    "Ag": 107.868,
    "Sn": 118.710,
    "Ba": 137.327,
    "W": 183.84,
    "Pt": 195.084,
    "Au": 196.967,
    "Pb": 207.2,
    "U": 238.029,
}

# Primary line → family satellites used to deconvolve overlapping IDs.
FAMILY_LINES = {"Ka": ("Kb",), "La": ("Lb", "Ma"), "Ma": ()}


def atomic_mass(symbol: str) -> float:
    if symbol in ATOMIC_MASS:
        return float(ATOMIC_MASS[symbol])
    try:
        return float(element(symbol)["Z"]) * 2.2
    except KeyError:
        return 50.0


def family_children(line: str) -> tuple[str, ...]:
    return FAMILY_LINES.get(str(line), ())
