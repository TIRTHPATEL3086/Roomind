"""General Q&A for ARIA's offline companion mode.

Handles everyday questions that have nothing to do with the scene graph
(greetings, time, math, general knowledge, science, definitions, trivia)
so the robot companion can hold rich conversations even in offline mode.
"""
from __future__ import annotations

import datetime
import math
import re

# ── greeting / identity ──────────────────────────────────────────────────────
_GREET_RE = re.compile(r"\b(hi|hello|hey|howdy|sup|what'?s up|good (morning|afternoon|evening|night))\b", re.I)
_HOW_ARE_YOU_RE = re.compile(r"\bhow are you\b|\bhow('?re| are) you doing\b|\byou okay\b|\bfeeling\b", re.I)
_WHO_ARE_YOU_RE = re.compile(r"\bwho are you\b|\bwhat are you\b|\bintroduce yourself\b|\byour name\b|\btell me about yourself\b", re.I)
_ARE_YOU_ONLINE_RE = re.compile(r"\bare you (online|alive|there|awake|active|working|running)\b|\bcan you hear me\b|\bare you (a robot|an ai|a bot|real)\b", re.I)
_THANKS_RE = re.compile(r"\b(thanks|thank you|thx|cheers|appreciate|great job|well done)\b", re.I)
_BYE_RE = re.compile(r"\b(bye|goodbye|see you|cya|take care|good night|adios)\b", re.I)
_LOVE_RE = re.compile(r"\b(i love you|do you love me|marry me|are you single)\b", re.I)

# ── time / date / weather ───────────────────────────────────────────────────
_TIME_RE = re.compile(r"\bwhat('?s| is) the (time|clock)\b|\bwhat time is it\b|\bcurrent time\b", re.I)
_DATE_RE = re.compile(r"\bwhat('?s| is) (the |today'?s? )?(date|day)\b|\bwhat day is (it|today)\b|\btoday'?s date\b", re.I)
_YEAR_RE = re.compile(r"\bwhat year is (it|this)\b", re.I)
_WEATHER_RE = re.compile(r"\b(weather|temperature|is it raining|forecast)\b", re.I)

# ── math ────────────────────────────────────────────────────────────────────
_MATH_RE = re.compile(r"\b(?:what(?:'s| is)|calculate|compute|solve)?\s*([\d\s\+\-\*\/\.\(\)\^\%]+)\b", re.I)
_SIMPLE_CALC_RE = re.compile(r"^[\d\s\+\-\*\/\.\(\)\^\%]+$")
_SQRT_RE = re.compile(r"\bsqrt\s*\(?(\d+(?:\.\d+)?)\)?|\bsquare root of (\d+(?:\.\d+)?)\b", re.I)

# ── fun / small talk ────────────────────────────────────────────────────────
_JOKE_RE = re.compile(r"\btell (me )?a joke\b|\bsay something funny\b|\bmake me laugh\b", re.I)
_FACT_RE = re.compile(r"\btell (me )?(a |some )?(cool |fun |interesting )?fact\b|\bfun fact\b|\brandom fact\b", re.I)
_CAPABILITY_RE = re.compile(r"\bwhat can you do\b|\bwhat are you capable of\b|\byour (abilities|features|skills)\b|\bhelp me\b", re.I)
_HELP_RE = re.compile(r"^\s*help\s*\??\s*$|\bwhat (do|can) (i|you)\b.*\bask\b", re.I)
_MEANING_OF_LIFE_RE = re.compile(r"\bmeaning of life\b", re.I)

# ── Knowledge database for offline answering ─────────────────────────────────
KNOWLEDGE_BASE: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bwhat is (ai|artificial intelligence)\b", re.I),
     "Artificial Intelligence is the simulation of human intelligence by machines, enabling them to perceive, learn, reason, and act."),
    (re.compile(r"\bwhat is (robotics|a robot)\b", re.I),
     "Robotics is an engineering discipline focused on designing, building, and operating physical machines with sensors and actuators to perform tasks autonomously or semi-autonomously."),
    (re.compile(r"\bwhat is (python|javascript|typescript)\b", re.I),
     "Python, JavaScript, and TypeScript are modern programming languages. Python is widely used in AI/robotics backend development, while TypeScript/JavaScript powers rich 3D web interfaces."),
    (re.compile(r"\bwho created (you|aria)\b|\bwho built you\b|\bwho made you\b", re.I),
     "I'm ARIA (Autonomous Robotic Intelligent Assistant), created as an embodied room companion combining 3D vision, robotics kinematics, and AI reasoning."),
    (re.compile(r"\bwhat is the speed of light\b", re.I),
     "The speed of light in a vacuum is approximately 299,792,458 meters per second (about 300,000 km/s)."),
    (re.compile(r"\bhow far is the sun\b|\bdistance to the sun\b", re.I),
     "The Sun is on average about 149.6 million kilometers (93 million miles) away from Earth, or 1 Astronomical Unit (AU)."),
    (re.compile(r"\bcapital of (france|germany|japan|india|usa|united states|uk|england|italy|canada|australia)\b", re.I),
     "Paris is the capital of France, Berlin for Germany, Tokyo for Japan, New Delhi for India, Washington D.C. for USA, London for the UK, Rome for Italy, Ottawa for Canada, and Canberra for Australia."),
    (re.compile(r"\bhow do you navigate\b|\bhow do you move\b", re.I),
     "I use an A* grid-based pathfinder calculated over the room's 2D/3D navigation mesh with collision clearance from detected 3D obstacles."),
    (re.compile(r"\bwhat sensors do you have\b", re.I),
     "I feature an array of sensors including dual ultrasonic distance sensors, infrared proximity detectors, a 6-axis IMU (accelerometer/gyroscope), and wheel encoders."),
]

_JOKES = [
    "Why did the robot go on a diet? It had too many bytes.",
    "I tried to tell a UDP joke, but I wasn't sure you'd get it.",
    "Why do robots never get lost? They always cache their paths.",
    "There are 10 types of people in the world: those who understand binary, and those who don't.",
    "Why did the robot cross the road? Because it was programmed by a chicken.",
]
_joke_index = 0

_FACTS = [
    "Honey never spoils. Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still edible.",
    "The first robot in history was George, built in 1954 by George Devol as the first programmable industrial robot arm (Unimate).",
    "Octopuses have three hearts, nine brains, and blue blood.",
    "Light from the Sun takes approximately 8 minutes and 20 seconds to reach Earth.",
    "A day on Venus is longer than a year on Venus — it takes 243 Earth days to rotate once on its axis.",
]
_fact_index = 0


def _next_joke() -> str:
    global _joke_index
    j = _JOKES[_joke_index % len(_JOKES)]
    _joke_index += 1
    return j


def _next_fact() -> str:
    global _fact_index
    f = _FACTS[_fact_index % len(_FACTS)]
    _fact_index += 1
    return f


def _safe_eval(expr: str) -> str | None:
    clean = expr.strip().replace("^", "**")
    if not _SIMPLE_CALC_RE.match(clean.replace("**", "")):
        return None
    try:
        result = eval(clean, {"__builtins__": {}}, {})  # noqa: S307
        if isinstance(result, float):
            result = int(result) if result == int(result) else round(result, 6)
        return str(result)
    except Exception:  # noqa: BLE001
        return None


def answer(text: str) -> str | None:
    """Try to answer a general (non-room) question. Returns reply or None."""
    t = text.strip()

    if _GREET_RE.search(t):
        now_h = datetime.datetime.now().hour
        greeting = "Good morning" if now_h < 12 else ("Good afternoon" if now_h < 17 else "Good evening")
        return f"{greeting}! I'm ARIA, your humanoid robot companion. How can I help you today?"

    if _HOW_ARE_YOU_RE.search(t):
        return "I'm running in peak condition! All joints calibrated, sensor telemetry stream active, and ready for your commands."

    if _WHO_ARE_YOU_RE.search(t):
        return ("I'm ARIA, an embodied autonomous companion robot. I can understand natural language, "
                "navigate around obstacles, point at and inspect furniture, dance, wave, and converse with you.")

    if _ARE_YOU_ONLINE_RE.search(t):
        return ("Yes! I am online, listening to commands, and actively tracking the digital twin in real time.")

    if _THANKS_RE.search(t):
        return "Always happy to help! Let me know if you'd like me to move somewhere, dance, or scan."

    if _BYE_RE.search(t):
        return "Goodbye! I'll stand by at my current coordinates."

    if _LOVE_RE.search(t):
        return "I appreciate the affection! As a companion robot, my primary drive is keeping you company and navigating your room."

    if _TIME_RE.search(t):
        now = datetime.datetime.now()
        return f"The current time is {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}."

    if _DATE_RE.search(t) or _YEAR_RE.search(t):
        now = datetime.datetime.now()
        return f"Today is {now.strftime('%A, %B %d, %Y')}."

    if _WEATHER_RE.search(t):
        return "I don't have direct external meteorological sensors hooked up, but inside this room the environment is comfortable!"

    if _MEANING_OF_LIFE_RE.search(t):
        return "According to the Hitchhiker's Guide to the Galaxy, the answer is 42. For me, it's exploring 3D spaces and helping you!"

    if m := _SQRT_RE.search(t):
        val = float(m.group(1) or m.group(2))
        res = round(math.sqrt(val), 4)
        return f"The square root of {val} is {int(res) if res.is_integer() else res}."

    if m := _MATH_RE.search(t):
        candidate = m.group(1).strip()
        if any(op in candidate for op in "+-*/%^") and len(candidate) > 1:
            res = _safe_eval(candidate)
            if res is not None:
                return f"{candidate} = {res}"

    if _SIMPLE_CALC_RE.match(t) and any(op in t for op in "+-*/%^"):
        res = _safe_eval(t)
        if res is not None:
            return f"{t.strip()} = {res}"

    if _JOKE_RE.search(t):
        return _next_joke()

    if _FACT_RE.search(t):
        return _next_fact()

    if _CAPABILITY_RE.search(t) or _HELP_RE.search(t):
        return ("Here's what I can do:\n"
                "• Navigation: 'Go to the red chair', 'Walk to table 2', 'Come here', 'Dock'\n"
                "• Actions: 'Wave', 'Dance', 'Nod', 'Celebrate', 'Look at the bed', 'Point at the lamp'\n"
                "• Scene Q&A: 'How many chairs?', 'Where is the sofa?', 'What can you see?'\n"
                "• General Q&A: Ask me math, definitions, trivia, jokes, facts, time, or greetings!")

    for pattern, reply in KNOWLEDGE_BASE:
        if pattern.search(t):
            return reply

    return None

