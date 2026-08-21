import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      // Proxy the API through Vite so the app is same-origin in dev: no CORS
      // preflight on every request, and the WebSocket upgrade just works.
      "/api": {
        // Port 8000 is stuck on a phantom Windows listen socket that outlasts
        // process kills and even survives PID reuse checks - see git history
        // for the investigation. Backend runs on 8010 instead until a reboot
        // clears it.
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        /**
         * Chunking is by module PATH, not by package name.
         *
         * The object form (`{gsap: ["gsap", ...]}`) only matches a package's
         * main entry, so `gsap/ScrollTrigger` and `gsap/SplitText` escaped into
         * a separate shared chunk that rollup then named after whichever module
         * it hashed first -- it was calling 21 kB of animation library
         * "reducedMotion". Matching on the path catches the subpath imports too.
         */
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          const p = id.replace(/\\/g, "/");
          // three + R3F is ~600 kB. Splitting it keeps the app shell small.
          if (/node_modules\/(three|@react-three)\//.test(p)) return "three";
          // Landing-only. If "gsap" ever appears in the entry chunk's static
          // imports, something re-coupled it to /app (spec 13.13).
          if (/node_modules\/(gsap|@gsap|lenis)\//.test(p)) return "gsap";
          return undefined;
        },
      },
    },
  },
});
