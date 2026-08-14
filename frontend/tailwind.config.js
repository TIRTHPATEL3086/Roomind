/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        /**
         * The page background. Named `night`, NOT `base`.
         *
         * A colour called `base` generates `.text-base { color: #0B1020 }`,
         * which collides with Tailwind's built-in `.text-base` font-size
         * utility -- and the colour wins, because colour utilities are emitted
         * later. So every `text-base` written as a FONT SIZE silently paints
         * the text in the page background colour and it disappears.
         *
         * That is not hypothetical: it shipped. The Phase 4 hero and body copy
         * both used `md:text-base` and were invisible at desktop widths, and
         * six card titles in the Phase 5 content sections went out the same
         * way. Nothing errors, nothing warns, and it is invisible in a diff.
         */
        night: "#0B1020",
        aria: "#3B82F6",
        glow: "#22D3EE",
        generated: "#A78BFA",
        danger: "#EF4444",
        ink: { DEFAULT: "#E5E7EB", muted: "#9CA3AF" },
      },
      /**
       * Every integer 0–100 as an opacity step.
       *
       * Tailwind's default scale only has 0, 5, 10, 20, 25, 30, 40, 50, 60,
       * 70, 75, 80, 90, 95, 100. Write `border-white/8` and the class is
       * simply NOT GENERATED — no error, no warning, and in a diff it looks
       * identical to `border-white/10`. The element then falls back to
       * Tailwind's default border colour, which on this dark UI is a bright
       * grey hairline instead of a barely-there one.
       *
       * That shipped too: `border-white/8`, `border-white/12`,
       * `border-white/15`, `border-white/35` and `text-white/12` were all
       * dead across the landing, the hero buttons and ObjectLabels.
       *
       * JIT only emits the ones actually used, so the full range costs
       * nothing.
       */
      opacity: Object.fromEntries(
        Array.from({ length: 101 }, (_, i) => [i, String(i / 100)]),
      ),
      fontFamily: {
        display: ["Space Grotesk", "sans-serif"],
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
      boxShadow: {
        glass: "0 8px 32px rgba(0,0,0,0.45)",
        glowAria: "0 0 24px #3B82F655",
      },
      backdropBlur: { glass: "18px" },
      borderRadius: { panel: "16px" },
    },
  },
  plugins: [],
};
