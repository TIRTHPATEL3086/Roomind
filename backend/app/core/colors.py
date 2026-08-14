"""Colour naming: a measured hex swatch -> a word a user would actually say.

This exists because "go to the red chair" has to be answered from something
measurable. The scene graph already carries a per-object `color` — the median
of the pixels the detector claimed for that object (S08 `_merge_color`), or the
designed colour for a fixture object. Turning that into a NAME is the only step
between a measurement and a query the user can type.

Two rules govern everything here:

  * Never invent a colour. If nothing was measured there is no colour attribute
    at all, and if the measurement is too washed out to name confidently the
    value is "unknown" with a low confidence — not a guess dressed as a fact.
  * The confidence is about the NAME, not the pixels. A swatch can be measured
    perfectly and still sit exactly on the boundary between orange and brown;
    that deserves a low confidence, because the user's word for it is a coin
    flip and the resolver must not silently pick a side.

Pure stdlib on purpose: this module is imported both by the API (which has no
numpy) and, over sys.path, by the reconstruction pipeline in its own venv —
the same sharing arrangement firmware/sim uses for kinematics. One colour
vocabulary, so a name the pipeline wrote is a name the resolver can match.
"""
from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass

HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")

# Below this saturation a colour has no hue worth naming — it is a grey, and
# which grey is decided by lightness alone.
ACHROMATIC_S = 0.16
# Below this lightness everything reads as black regardless of hue. A #111827
# television is "black" to every human who looks at it, even though its hue is
# a perfectly valid blue.
BLACK_L = 0.16
WHITE_L = 0.88

# Hue buckets in degrees, as (name, start, end]. Wrapping red is handled by
# listing it at both ends. These are the *display* names — see FAMILIES for
# what a user's word is allowed to match.
_HUE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("red",     340.0, 360.0),
    ("red",       0.0,  14.0),
    ("orange",   14.0,  40.0),
    ("yellow",   40.0,  68.0),
    ("green",    68.0, 160.0),
    ("cyan",    160.0, 195.0),
    ("blue",    195.0, 255.0),
    ("purple",  255.0, 290.0),
    ("pink",    290.0, 340.0),
)

# Red is the one bucket that wraps, so its centre is 0 and not the midpoint of
# either half. Scoring it as two ordinary buckets puts pure red (#C62828, hue 0)
# hard against an edge and reports ~0.5 confidence for the least ambiguous
# colour there is.
_RED_HALF_WIDTH = 17.0

# Words a user might say -> the canonical name they should match. A query is
# normalised through this before comparison, so "grey" and "gray" are the same
# question and "teal" finds a cyan cushion.
SYNONYMS: dict[str, str] = {
    "gray": "grey", "grey": "grey", "silver": "grey", "charcoal": "grey",
    "black": "black", "dark": "black",
    "white": "white", "cream": "beige", "ivory": "beige", "beige": "beige",
    "tan": "beige", "off-white": "white",
    "red": "red", "maroon": "red", "crimson": "red", "burgundy": "red",
    "scarlet": "red",
    "orange": "orange", "amber": "orange",
    "brown": "brown", "wooden": "brown", "wood": "brown", "walnut": "brown",
    "oak": "brown", "chocolate": "brown",
    "yellow": "yellow", "gold": "yellow", "golden": "yellow", "mustard": "yellow",
    "green": "green", "olive": "green", "lime": "green", "emerald": "green",
    "cyan": "cyan", "teal": "cyan", "turquoise": "cyan", "aqua": "cyan",
    "blue": "blue", "navy": "blue", "azure": "blue", "cobalt": "blue",
    "purple": "purple", "violet": "purple", "lilac": "purple", "lavender": "purple",
    "magenta": "pink", "pink": "pink", "rose": "pink",
}

# Names that a query for the key should also accept. Deliberately narrow and
# one-directional: asking for "brown" accepts a beige sofa (they are the same
# thing to most people at furniture scale), but asking for "beige" does not
# accept a dark walnut one.
FAMILIES: dict[str, frozenset[str]] = {
    "brown": frozenset({"brown", "beige", "orange"}),
    "grey": frozenset({"grey", "silver"}),
    "black": frozenset({"black"}),
    "white": frozenset({"white", "beige"}),
    "beige": frozenset({"beige"}),
    "blue": frozenset({"blue", "cyan"}),
    "purple": frozenset({"purple", "pink"}),
}

ALL_NAMES = frozenset(
    {"black", "white", "grey", "beige", "brown", "red", "orange", "yellow",
     "green", "cyan", "blue", "purple", "pink"}
)


@dataclass(frozen=True)
class ColorName:
    """A named colour and how much the name should be trusted."""

    value: str          # canonical name, or "unknown"
    hex: str            # the measurement it came from, normalised to #RRGGBB
    confidence: float   # 0..1, about the NAME

    def as_dict(self) -> dict:
        return {"value": self.value, "hex": self.hex,
                "confidence": round(self.confidence, 3)}


def parse_hex(value: str) -> tuple[int, int, int] | None:
    m = HEX_RE.match((value or "").strip())
    if not m:
        return None
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(float(v))))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _bucket_confidence(hue: float, start: float, end: float) -> float:
    """How central `hue` sits in its bucket, 0 at an edge and 1 in the middle.

    A hue one degree from the orange/yellow line is genuinely ambiguous and the
    confidence has to say so, otherwise the resolver treats a coin flip as a
    fact and quietly drives to the wrong chair.
    """
    half = (end - start) / 2.0
    if half <= 0:
        return 0.5
    centre = start + half
    return max(0.0, 1.0 - abs(hue - centre) / half)


def name_hex(value: str | None) -> ColorName | None:
    """Measured swatch -> named colour. None when there was no measurement.

    Returning None rather than a default is the point: absence of a colour and
    a colour we could not name are different states, and only the first one
    means "the detector never told us".
    """
    if not value:
        return None
    rgb = parse_hex(value)
    if rgb is None:
        return None

    r, g, b = (c / 255.0 for c in rgb)
    hue_f, light, sat = colorsys.rgb_to_hls(r, g, b)
    hue = hue_f * 360.0
    normalised = to_hex(rgb)

    # Lightness decides first. Hue survives at both extremes but stops meaning
    # anything: nobody calls #0A0A12 "dark blue furniture", they call it black.
    if light <= BLACK_L:
        conf = 0.75 + 0.25 * min(1.0, (BLACK_L - light) / max(BLACK_L, 1e-6))
        return ColorName("black", normalised, min(0.98, conf))
    if light >= WHITE_L and sat < 0.35:
        conf = 0.75 + 0.25 * min(1.0, (light - WHITE_L) / max(1.0 - WHITE_L, 1e-6))
        return ColorName("white", normalised, min(0.98, conf))

    if sat < ACHROMATIC_S:
        # Genuinely neutral. Confidence rises as saturation falls — a swatch
        # sitting just under the threshold could reasonably be called by its
        # hue instead.
        conf = 0.45 + 0.5 * (1.0 - sat / ACHROMATIC_S)
        # Beige is the one neutral users name by warmth rather than lightness.
        if light > 0.62 and 15.0 <= hue <= 65.0 and sat > 0.06:
            return ColorName("beige", normalised, min(0.9, conf * 0.9))
        return ColorName("grey", normalised, min(0.95, conf))

    name = "unknown"
    conf = 0.4
    for bucket, start, end in _HUE_BUCKETS:
        if start <= hue < end or (end == 360.0 and hue >= start):
            name = bucket
            if bucket == "red":
                # signed distance from 0, the wrap point
                offset = min(hue, 360.0 - hue)
                conf = 0.55 + 0.4 * max(0.0, 1.0 - offset / _RED_HALF_WIDTH)
            else:
                conf = 0.55 + 0.4 * _bucket_confidence(hue, start, end)
            break

    # Brown is not a hue, it is a dark or muted ORANGE, and it is the single
    # most common furniture colour there is. Without this branch every wooden
    # table comes back "orange" and "go to the brown table" finds nothing.
    #
    # Gated on hue, not on lightness alone. A crimson #C62828 is dark enough
    # (L 0.47) to pass a pure lightness test and would come back "brown", which
    # is wrong in a way the user notices immediately: its hue is 0, and brown
    # lives in the orange band. The lightness ceiling is 0.50 rather than 0.42
    # because #8A6B4F — the demo room's oak table — sits at 0.425, and a
    # threshold that excludes the most typical wood tone in the fixture is
    # measuring the wrong thing.
    if 10.0 <= hue < 50.0 and light < 0.50 and sat < 0.85:
        name = "brown"
        conf = max(conf, 0.7)
    elif name in ("orange", "yellow") and light >= 0.60 and sat < 0.55:
        # Pale warm tones are beige, not a vivid orange or yellow. A cream
        # lampshade called "yellow" fails every query a user would type at it.
        name = "beige"
        conf = max(conf * 0.9, 0.55)

    # A washed-out hue is a weaker claim than a vivid one.
    conf *= 0.65 + 0.35 * min(1.0, sat / 0.5)
    return ColorName(name, normalised, max(0.15, min(0.98, conf)))


def canonical(word: str) -> str | None:
    """A user's colour word -> the canonical name, or None if it isn't one."""
    w = (word or "").strip().lower().replace("_", "-")
    if w in SYNONYMS:
        return SYNONYMS[w]
    return w if w in ALL_NAMES else None


def matches(query_word: str, color: dict | ColorName | None) -> bool:
    """Does an object's measured colour answer the user's colour word?

    False for a missing colour, always. "The red chair" must not match a chair
    whose colour was never measured — that would be inventing the attribute at
    query time instead of at detection time, which is the same lie either way.
    """
    want = canonical(query_word)
    if want is None or color is None:
        return False
    got = color.value if isinstance(color, ColorName) else color.get("value")
    if not got:
        return False
    got = got.lower()
    if got == want:
        return True
    return got in FAMILIES.get(want, frozenset())


def is_color_word(word: str) -> bool:
    return canonical(word) is not None
