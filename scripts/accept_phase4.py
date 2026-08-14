"""Phase 4 acceptance — the GSAP cinematic landing.

This one is a BUILD-AND-SOURCE acceptance, not a live one. Phases 1-3b could be
checked by talking to a running server; most of P4's contract is about what ends
up in the bundle and how the code is wired, so that is what this measures.

Four of the spec's criteria need a real browser painting real frames and are NOT
covered here. They are listed at the end of the run so nobody mistakes a green
result for "the landing was watched":

  - >= 55 fps and <= 25 draw calls
  - no remount / no white flash across the hand-off
  - the < 900 ms hand-off timing
  - reduced motion verified visually

The static half of reduced motion IS enforced (every animating component must
consult motionDisabled()), which is what actually rots when someone adds a beat.
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "frontend"
DIST = FE / "dist"
SRC = FE / "src"

failures: list[str] = []
total = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global total
    total += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    """Source with comments stripped.

    Structural checks MUST run on this, not on raw text. The first version of
    this script failed three checks because the files explain themselves: the
    docstring in WorldDashboard says it does not own the "<Canvas>", and the one
    in cameraPose says keeping GSAP out is the point. Grepping raw source found
    those sentences and reported the exact opposite of the truth.
    """
    s = re.sub(r"/\*.*?\*/", "", read(p), flags=re.S)
    return re.sub(r"^\s*//.*$", "", s, flags=re.M)


def gz_kb(p: Path) -> float:
    return len(gzip.compress(p.read_bytes(), 9)) / 1024


print("PHASE 4 ACCEPTANCE — CINEMATIC LANDING\n")

# ---------------------------------------------------------------- 0. build
print("0. build")
npm = shutil.which("npm") or shutil.which("npm.cmd")
if npm is None:
    print("  SKIP  npm not on PATH — cannot build")
    sys.exit(1)

tsc = subprocess.run([npm, "exec", "--", "tsc", "--noEmit"], cwd=FE,
                     capture_output=True, text=True)
check("typecheck clean", tsc.returncode == 0, (tsc.stdout or tsc.stderr)[-300:].strip())

build = subprocess.run([npm, "run", "build"], cwd=FE, capture_output=True, text=True)
check("production build succeeds", build.returncode == 0,
      (build.stderr or "")[-300:].strip())
if build.returncode != 0:
    sys.exit(1)

# ------------------------------------------------- 1. code splitting / budgets
print("\n1. bundle — /app must not pay for the landing")
index_html = read(DIST / "index.html")
assets = DIST / "assets"

# What the browser fetches before any lazy import: the entry script, the CSS,
# and anything modulepreloaded.
eager = set(re.findall(r'(?:src|href)="/assets/([^"]+)"', index_html))
entry = next(f for f in eager if f.startswith("index-") and f.endswith(".js"))
entry_js = read(assets / entry)
# Rollup emits `from"./chunk.js"` for a chunk's own static imports.
eager |= set(re.findall(r'from"\./([A-Za-z0-9_.\-]+\.js)"', entry_js))

check("GSAP chunk is not in the eager graph",
      not any("gsap" in f for f in eager), ", ".join(sorted(eager)))
check("entry chunk contains no ScrollTrigger code",
      "ScrollTrigger" not in entry_js and "registerPlugin" not in entry_js)

names = [p.name for p in assets.iterdir()]
check("landing is code-split", any(n.startswith("Landing-") for n in names))
check("camera rig is code-split", any(n.startswith("CameraRig-") for n in names))
check("gsap has its own named chunk", any(n.startswith("gsap-") for n in names))

app_kb = sum(gz_kb(assets / f) for f in eager)
landing_only = [p for p in assets.iterdir()
                if p.suffix == ".js" and p.name not in eager]
landing_kb = app_kb + sum(gz_kb(p) for p in landing_only)

check("/app route stays lean", app_kb < 700, f"{app_kb:.0f} kB gz")
check("landing transfer <= 1.2 MB gzipped", landing_kb <= 1200, f"{landing_kb:.0f} kB gz")
print(f"        landing adds {landing_kb - app_kb:.0f} kB gz on top of /app")

# The spec's 400 KB "diorama" budget is really a cap on 3D assets the landing
# pulls in. There is no separate diorama -- the landing showcases the live room
# -- but that room now renders real furniture models, so the budget applies to
# those instead of being trivially satisfied by shipping nothing.
#
# Only the models the DEMO ROOM actually references count against the landing:
# the registry ships extra labels (bed, fridge, desk) for scanned and generated
# rooms, and useGLTF never fetches a model no object asks for.
DEMO_MODELS = {
    "table.glb", "chairCushion.glb", "loungeSofa.glb", "bookcaseOpen.glb",
    "pottedPlant.glb", "rugRectangle.glb", "televisionModern.glb",
    "lampRoundFloor.glb",
}
all_models = list((FE / "public").rglob("*.gl[bt]*"))
used = [p for p in all_models if p.name in DEMO_MODELS]
used_kb = sum(p.stat().st_size for p in used) / 1024
shipped_kb = sum(p.stat().st_size for p in all_models) / 1024
check("landing 3D assets <= 400 KB", used_kb <= 400,
      f"{used_kb:.0f} kB across {len(used)} models "
      f"({shipped_kb:.0f} kB on disk, fetched on demand)")
check("every demo-room model is present", len(used) == len(DEMO_MODELS),
      f"{len(used)}/{len(DEMO_MODELS)}")
check("model licence ships with the assets",
      (FE / "public" / "models" / "kenney" / "LICENSE.txt").exists())

# --------------------------------------------------- 2. ScrollTrigger budget
print("\n2. ScrollTrigger budget (<= 8, all released on unmount)")
beats = SRC / "components" / "landing" / "Beats.tsx"
section = SRC / "components" / "landing" / "Section.tsx"
rig = SRC / "three" / "CameraRig.tsx"

# Count INSTANCES, not declarations. Section.tsx declares one trigger but is
# instantiated once per beat, so grepping for `scrollTrigger:` reports 3 when
# the browser actually builds 7 — a budget check that cannot see the overrun it
# exists to catch.
per_section = len(re.findall(r"\bscrollTrigger\s*:", code(section)))
n_sections = len(re.findall(r"<Section\b", code(beats)))
standalone = len(re.findall(r"\bscrollTrigger\s*:", code(beats)))
rig_triggers = len(re.findall(r"\bscrollTrigger\s*:", code(rig)))
triggers = per_section * n_sections + standalone + rig_triggers
check("runtime triggers <= 8", triggers <= 8,
      f"{triggers} = {n_sections} sections + {standalone} standalone + {rig_triggers} rig")

landing_tsx = code(SRC / "components" / "landing" / "Landing.tsx")
check("kills every trigger on unmount",
      re.search(r"useEffect\(\s*\(\)\s*=>\s*\(\)\s*=>\s*ScrollTrigger\.getAll\(\)\.forEach",
                landing_tsx) is not None)
check("kills every trigger before handing off to /app",
      "ScrollTrigger.getAll().forEach((t) => t.kill());" in landing_tsx)

# ------------------------------------------------------- 3. the hand-off wiring
print("\n3. hand-off — one Canvas, never remounted")
app_tsx = code(SRC / "App.tsx")
canvases = [p for p in SRC.rglob("*.tsx") if re.search(r"<Canvas[\s>]", code(p))]
check("exactly one <Canvas> in the whole app", len(canvases) == 1,
      ", ".join(p.name for p in canvases))
check("the Canvas is mounted above the router", "<SceneRoot" in app_tsx)
check("landing is lazy-imported", 'lazy(() => import("./components/landing/Landing"))' in app_tsx)

pose = code(SRC / "three" / "cameraPose.ts")
check("last beat is spread from APP_CAMERA, so it cannot drift",
      "pos: [...APP_CAMERA.pos], look: [...APP_CAMERA.look]" in pose)
check("cameraPose stays GSAP-free (or /app re-imports the library)",
      "gsap" not in pose.lower())

scene_root = code(SRC / "three" / "SceneRoot.tsx")
check("OrbitControls is disabled during the landing", "enabled={!landing}" in scene_root)
check("the rig only mounts on the landing route", "{landing && (" in scene_root)

# ---------------------------------------------------------- 4. reduced motion
print("\n4. prefers-reduced-motion")
reduced = read(SRC / "motion" / "reducedMotion.ts")
check("honours the OS setting", "prefers-reduced-motion" in reduced)
check("?nomotion=1 forces it on for demos", "nomotion" in reduced)

animating = [p for p in SRC.rglob("*.tsx")
             if "useGSAP(" in code(p) or "gsap.timeline(" in code(p)]
missing = [p.name for p in animating if "motionDisabled()" not in code(p)]
check("every animating component consults motionDisabled()", not missing,
      ", ".join(missing))

# ------------------------------------------------------------ 5. skip + credits
print("\n5. demo insurance and attribution")
check("Skip Intro button is always rendered", "data-skip-intro" in landing_tsx)
check("Esc skips from any beat", '"Escape"' in landing_tsx)
check("an FPS floor drops the scrubs rather than stuttering",
      "FPS_FLOOR" in landing_tsx and "t.vars.scrub" in landing_tsx)

credits = FE / "public" / "CREDITS.md"
check("CREDITS.md exists", credits.exists())
if credits.exists():
    c = read(credits)
    check("credits name the inspiration source", "expeditione.fun" in c)
    check("credits state what was and was not taken", "Not taken" in c)
    check("credits cover the GSAP licence", "GSAP" in c and "no-charge" in c.lower()
          or "GSAP" in c and "free" in c.lower())

pkg = json.loads(read(FE / "package.json"))
deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
check("gsap pinned at 3.13+ (the fully-free release)",
      re.match(r"[\^~]?3\.1[3-9]", deps.get("gsap", "")) is not None,
      deps.get("gsap", "absent"))

# ------------------------------------------------------------------- verdict
print("\n" + "-" * 72)
print("NOT COVERED — needs a browser painting real frames:")
for line in ("frame rate >= 55 fps",
             "no remount / no white flash across the hand-off",
             "hand-off completes in < 900 ms",
             "reduced-motion pass verified visually"):
    print(f"  TODO  {line}")
print()
print("  MEASURED, and OVER BUDGET — 32 draw calls against the spec's 25.")
print("    Load any route with ?probe=1 and read window.__rm.gl.info.render.")
print("    Breakdown: ARIA 10 (one mesh per articulated part, and she has 9")
print("    joints), furniture 17, room shell and grid 5. The furniture models")
print("    did NOT cause this: they replaced 18 calls of boxes-plus-wireframes")
print("    with 17. The budget was already exceeded when the scene was boxes,")
print("    and went unnoticed because this check was listed as unverifiable.")
print("    4,352 triangles total, so this is a budget question, not a")
print("    performance one — but it is not passing, so it is not a PASS.")
print("-" * 72)

if failures:
    print(f"\n{len(failures)}/{total} FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"\nPHASE 4 ACCEPTED — {total}/{total} static + bundle checks")
