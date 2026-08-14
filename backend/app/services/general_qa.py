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
    # AI & Technology
    (re.compile(r"\bwhat is (ai|artificial intelligence)\b", re.I),
     "Artificial Intelligence is the simulation of human intelligence by machines — enabling them to learn, reason, plan, and act. It includes machine learning, deep learning, NLP, and robotics."),
    (re.compile(r"\bwhat is machine learning\b", re.I),
     "Machine Learning is a subset of AI where systems learn patterns from data without being explicitly programmed. It includes supervised, unsupervised, and reinforcement learning."),
    (re.compile(r"\bwhat is deep learning\b", re.I),
     "Deep Learning uses neural networks with many layers to learn complex patterns from large datasets — powering image recognition, language models, and autonomous driving."),
    (re.compile(r"\bwhat is (chatgpt|gpt)\b", re.I),
     "ChatGPT is an AI assistant made by OpenAI, based on GPT (Generative Pre-trained Transformer) large language models trained on vast text data."),
    (re.compile(r"\bwhat is (gemini)\b", re.I),
     "Gemini is Google DeepMind's multimodal AI model that can understand text, images, audio, video, and code simultaneously."),
    (re.compile(r"\bwhat is (robotics|a robot)\b", re.I),
     "Robotics is an engineering discipline focused on designing, building, and operating machines with sensors and actuators that can perform tasks autonomously."),
    (re.compile(r"\bwhat is (python|javascript|typescript)\b", re.I),
     "Python is a versatile language used in AI, data science, and backend development. JavaScript/TypeScript power the web. TypeScript adds static types to JavaScript."),
    (re.compile(r"\bwhat is (blockchain|bitcoin|cryptocurrency)\b", re.I),
     "Blockchain is a distributed ledger technology. Bitcoin is the first cryptocurrency, a decentralized digital currency using blockchain. Crypto refers to digital currencies secured by cryptography."),
    (re.compile(r"\bwhat is (cloud computing|the cloud)\b", re.I),
     "Cloud computing delivers computing services (servers, storage, databases, AI) over the internet, allowing access from anywhere without owning physical hardware."),
    (re.compile(r"\bwhat is (iot|internet of things)\b", re.I),
     "The Internet of Things (IoT) refers to physical devices embedded with sensors and connectivity, enabling them to collect and share data — like smart home devices, wearables, and industrial sensors."),
    # Science & Physics
    (re.compile(r"\bwhat is the speed of light\b", re.I),
     "The speed of light in a vacuum is exactly 299,792,458 m/s (~300,000 km/s or 186,000 miles/s). Nothing with mass can travel faster."),
    (re.compile(r"\bwhat is (gravity|gravitation)\b", re.I),
     "Gravity is the fundamental force that attracts objects with mass toward each other. On Earth, it accelerates objects at 9.8 m/s². Described by Newton's law and Einstein's general relativity."),
    (re.compile(r"\bwhat is (quantum mechanics|quantum physics)\b", re.I),
     "Quantum mechanics describes the behavior of matter and energy at atomic/subatomic scales, where particles can exist in superpositions and exhibit wave-particle duality."),
    (re.compile(r"\bwhat is (relativity|einstein's theory)\b", re.I),
     "Einstein's Theory of Relativity has two parts: Special Relativity (1905) — time dilates and mass increases at high speeds; General Relativity (1915) — gravity is the curvature of spacetime."),
    (re.compile(r"\bwhat is (dna|rna)\b", re.I),
     "DNA (Deoxyribonucleic Acid) is the molecule that carries genetic instructions in all living organisms. RNA carries DNA's instructions to make proteins."),
    (re.compile(r"\bwhat is (photosynthesis)\b", re.I),
     "Photosynthesis is the process by which plants use sunlight, water, and CO₂ to produce glucose and oxygen: 6CO₂ + 6H₂O + light → C₆H₁₂O₆ + 6O₂."),
    (re.compile(r"\bwhat is (evolution|darwinism|natural selection)\b", re.I),
     "Evolution is the process of gradual change in species over generations through natural selection — organisms with favorable traits reproduce more, shaping future generations."),
    (re.compile(r"\bhow far is the sun\b|\bdistance to the sun\b", re.I),
     "The Sun is on average 149.6 million km (93 million miles / 1 AU) from Earth. Light takes ~8 min 20 sec to reach us."),
    (re.compile(r"\bhow far is the moon\b|\bdistance (to|of) the moon\b", re.I),
     "The Moon is on average 384,400 km (238,855 miles) from Earth. It takes light about 1.28 seconds to travel that distance."),
    # Space & Astronomy
    (re.compile(r"\bhow many planets (are there|in (our|the) solar system)\b", re.I),
     "There are 8 planets in our solar system: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, and Neptune. Pluto was reclassified as a dwarf planet in 2006."),
    (re.compile(r"\bwhat is a black hole\b", re.I),
     "A black hole is a region in space with gravity so strong that nothing — not even light — can escape. They form when massive stars collapse. The boundary is called the event horizon."),
    (re.compile(r"\bwhat is (the big bang)\b", re.I),
     "The Big Bang is the prevailing theory for the origin of the universe — approximately 13.8 billion years ago, all matter and energy exploded from an extremely hot, dense point."),
    (re.compile(r"\bwhat is (the milky way)\b", re.I),
     "The Milky Way is the galaxy containing our Solar System — a barred spiral galaxy containing 200–400 billion stars, approximately 105,000 light-years in diameter."),
    # Geography & Capitals
    (re.compile(r"\bcapital of (france|paris)\b", re.I), "The capital of France is Paris."),
    (re.compile(r"\bcapital of (germany)\b", re.I), "The capital of Germany is Berlin."),
    (re.compile(r"\bcapital of (japan)\b", re.I), "The capital of Japan is Tokyo."),
    (re.compile(r"\bcapital of (india)\b", re.I), "The capital of India is New Delhi."),
    (re.compile(r"\bcapital of (usa|united states|america)\b", re.I), "The capital of the USA is Washington, D.C."),
    (re.compile(r"\bcapital of (uk|england|britain)\b", re.I), "The capital of the United Kingdom is London."),
    (re.compile(r"\bcapital of (australia)\b", re.I), "The capital of Australia is Canberra (not Sydney)."),
    (re.compile(r"\bcapital of (china)\b", re.I), "The capital of China is Beijing."),
    (re.compile(r"\bcapital of (russia)\b", re.I), "The capital of Russia is Moscow."),
    (re.compile(r"\bcapital of (brazil)\b", re.I), "The capital of Brazil is Brasília (not Rio de Janeiro)."),
    (re.compile(r"\blargest country\b", re.I), "Russia is the largest country in the world by area, covering 17.1 million km² — about twice the size of the second-largest, Canada."),
    (re.compile(r"\bsmallest country\b", re.I), "Vatican City is the smallest country in the world, covering 0.44 km² inside Rome, Italy."),
    (re.compile(r"\blongest river\b", re.I), "The Nile in Africa is traditionally the longest river at ~6,650 km, though some measurements give the Amazon a slight edge."),
    (re.compile(r"\bhighest mountain\b|\btallest mountain\b", re.I), "Mount Everest in the Himalayas is the highest mountain above sea level at 8,849 m (29,032 ft)."),
    # History
    (re.compile(r"\bwho was (mahatma gandhi|gandhi)\b", re.I),
     "Mahatma Gandhi (1869–1948) was the leader of India's independence movement, pioneering nonviolent civil disobedience (Satyagraha) that inspired movements worldwide."),
    (re.compile(r"\bwho was (albert einstein)\b", re.I),
     "Albert Einstein (1879–1955) was a German-born physicist who developed the theories of Special and General Relativity, and won the 1921 Nobel Prize in Physics."),
    (re.compile(r"\bwhen did (world war 2|ww2|second world war) (start|end|happen)\b", re.I),
     "World War 2 started on September 1, 1939 when Germany invaded Poland, and ended on September 2, 1945 with Japan's surrender."),
    (re.compile(r"\bwhen did (world war 1|ww1|first world war) (start|end|happen)\b", re.I),
     "World War 1 started on July 28, 1914 and ended on November 11, 1918."),
    (re.compile(r"\bwho invented (the telephone)\b", re.I),
     "Alexander Graham Bell is credited with inventing the telephone in 1876, though Elisha Gray filed a patent on the same day."),
    (re.compile(r"\bwho invented (the internet)\b", re.I),
     "The internet evolved from ARPANET (1969). Tim Berners-Lee invented the World Wide Web in 1989–1991, making it publicly accessible."),
    (re.compile(r"\bwho invented (electricity|light bulb)\b", re.I),
     "Thomas Edison invented the practical incandescent light bulb in 1879. Electricity itself was studied by many including Benjamin Franklin and Michael Faraday."),
    # Math
    (re.compile(r"\bwhat is pi\b|\bvalue of pi\b", re.I),
     "Pi (π) ≈ 3.14159265358979... It is the ratio of a circle's circumference to its diameter, an irrational and transcendental number."),
    (re.compile(r"\bwhat is (pythagoras|pythagorean theorem)\b", re.I),
     "The Pythagorean Theorem states that in a right triangle, a² + b² = c², where c is the hypotenuse."),
    (re.compile(r"\bwhat is (fibonacci|fibonacci sequence)\b", re.I),
     "The Fibonacci sequence: 0, 1, 1, 2, 3, 5, 8, 13, 21... Each number is the sum of the two before it. It appears throughout nature."),
    # Biology & Health
    (re.compile(r"\bhow many (bones|bones in the human body)\b", re.I),
     "The adult human body has 206 bones. Babies are born with ~270, which fuse over time."),
    (re.compile(r"\bhow many (organs|organs in the human body)\b", re.I),
     "The human body has 78 major organs, including vital ones: heart, brain, lungs, liver, kidneys, and skin (the largest organ)."),
    (re.compile(r"\bwhat is the (heart|human heart)\b", re.I),
     "The heart is a muscular organ that pumps blood throughout the body. It beats ~100,000 times a day, circulating ~5 liters of blood per minute."),
    # Robot self-knowledge
    (re.compile(r"\bwho created (you|aria)\b|\bwho built you\b|\bwho made you\b", re.I),
     "I'm ARIA (Autonomous Robotic Intelligent Assistant) — a humanoid room companion combining 3D vision, A* navigation, kinematics, and AI reasoning."),
    (re.compile(r"\bhow do you navigate\b|\bhow do you move\b", re.I),
     "I use an A* grid-based pathfinder on the room's 2D nav mesh, with collision clearance computed from 3D obstacle bounds."),
    (re.compile(r"\bwhat sensors do you have\b", re.I),
     "I have ultrasonic distance sensors, infrared proximity detectors, a 6-axis IMU (accelerometer/gyroscope), and wheel encoders."),
    (re.compile(r"\bwhat joints do you have\b|\bcan you (sit|jump|climb|dance)\b", re.I),
     "I have 9 controllable joints: head pan/tilt, waist yaw, left/right shoulder pitch/roll, left/right elbow — plus leg joints for hip and knee articulation. I can sit, jump, climb, dance, wave, and more!"),
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

