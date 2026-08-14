# RoomMind — Credits & Licences

Every third-party asset and library in this build, with its licence. If it is not
listed here, it is not in the build.

## Libraries

| Library | Licence | Notes |
|---|---|---|
| GSAP 3.13 | GreenSock Standard License | **Free, including commercial use**, since April 2025 (Webflow acquired GreenSock Oct 2024). All formerly Club-only plugins — ScrollTrigger, SplitText, MorphSVG, DrawSVG, ScrollSmoother — are included at no charge. No licence key, no attribution required. <https://gsap.com/community/standard-license/> |
| @gsap/react 2.1.2 | GreenSock Standard License | `useGSAP()` hook |
| Lenis 1.1.13 | MIT | Smooth scroll, landing route only |
| Three.js 0.169 | MIT | |
| React Three Fiber / drei | MIT | |
| React 18.3 | MIT | |
| Zustand, framer-motion | MIT | |
| Lucide icons | ISC | |
| Vite, TypeScript, TailwindCSS | MIT | |

## Fonts

| Font | Licence |
|---|---|
| Inter | SIL Open Font License 1.1 |
| Space Grotesk | SIL Open Font License 1.1 |
| JetBrains Mono | SIL Open Font License 1.1 |

Served from Google Fonts.

## 3D assets

| Asset | Source | Licence |
|---|---|---|
| Furniture models (`public/models/kenney/`) | **Kenney — "Furniture Kit"**, <https://kenney.nl/assets/furniture-kit> | **CC0 1.0 Universal** (public domain) |

Kenney releases his asset packs into the public domain. **No attribution is
legally required** — this entry exists because saying where the art came from is
simply correct, and because a future reader deserves to know which meshes were
authored here and which were not. The pack's own licence text ships next to the
models at `public/models/kenney/LICENSE.txt`.

18 models are in the repository (187 KB total, uncompressed). Only the 8 the
demo room references are ever fetched by a browser; the rest exist so scanned
and generated rooms can resolve labels like `bed`, `desk` or `fridge`. They are
served as-is — no Draco compression, because a Draco decoder is larger than the
entire model set.

**Everything else is still generated at runtime**: the room shell, ARIA's rigged
body, the navmesh path line, the selection wireframes, and the Imagine proxy
objects are all built from Three.js primitives in code. Objects produced by the
Imagine feature are generated from the user's own uploaded image; those images
belong to the user and are never redistributed.

Downloaded models are **recoloured at runtime** to the scene graph's own palette
so they match the interface, and **scaled to the detected metric dimensions** so
the visible object occupies exactly the volume the path planner avoids. The
geometry is Kenney's; the size, orientation and colour are ours.

## Inspiration — no code, assets, or copy taken

The visual and motion direction of the landing page is inspired by the
scroll-driven 3D storytelling of **expeditione.fun** by **Aureon de Veyra**.

To be unambiguous about what that means:

- **Taken:** the *techniques* — scroll-choreographed camera movement, one idea
  per viewport, restraint in the layout, a strict asset budget. Techniques are
  not copyrightable and are freely reusable.
- **Not taken:** its code, 3D models, textures, shaders, sounds, SVGs,
  copywriting, section names, colour palette, and brand marks. None of it was
  copied, adapted, or referenced at the file level.

RoomMind is **not affiliated with Expeditione** and does not claim to be.
Expeditione is an original, all-rights-reserved work with no public repository
and no licence grant — it is not a template, and it was not treated as one.

GSAP, the library Expeditione is built with, is separately and fully free for
anyone to use (see the table above). We took the library and the craft, never
the artefact.

## Sound

None. RoomMind ships no audio assets. Speech uses the browser's built-in
`SpeechSynthesis` API.
