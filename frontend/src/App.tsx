import { Suspense, lazy, useEffect } from "react";

import { getRoom, resetRoom } from "./api/client";
import { connectWS, disconnectWS } from "./api/ws";
import { WorldDashboard } from "./components/WorldDashboard";
import { useRoute } from "./hooks/useRoute";
import { useSceneStore } from "./store/sceneStore";
import { SceneRoot } from "./three/SceneRoot";

/**
 * The landing is code-split so /app never downloads the GSAP scroll story.
 * `/app` is the bookmark used to open the pitch — it must load standalone and
 * as small as possible (spec 13.12, 13.13).
 */
const Landing = lazy(() => import("./components/landing/Landing"));

export default function App() {
  const [route, navigate] = useRoute();
  const landing = route === "landing";
  const roomId = useSceneStore((s) => s.roomId);

  /**
   * Scene + socket live at the app root, not inside a route.
   *
   * The landing renders the real room, so it needs the same scene graph the
   * dashboard does — and loading it once here means the hand-off has nothing
   * left to fetch. A spinner appearing the instant you click "Enter your
   * world" would undo the entire seamless transition.
   */
  // Re-runs on a room switch: the socket is subscribed per room, so changing
  // rooms means fetching the new graph AND resubscribing, or the dashboard
  // would render one room while receiving another's telemetry.
  useEffect(() => {
    let cancelled = false;
    useSceneStore.getState().setLoading(true);
    // On page load or fresh reload, reset the demo room so uploaded transient objects
    // are cleared and default furniture is cleanly restored
    resetRoom(roomId)
      .then((g) => {
        if (!cancelled) useSceneStore.getState().setGraph(g);
      })
      .catch(() => {
        // Fallback to getRoom if reset fails
        return getRoom(roomId).then((g) => {
          if (!cancelled) useSceneStore.getState().setGraph(g);
        });
      })
      .catch((e) => {
        if (!cancelled) {
          useSceneStore
            .getState()
            .setError(
              `Could not load the room: ${e.message}. Is the backend running on :8000?`,
            );
        }
      })
      .finally(() => useSceneStore.getState().setLoading(false));

    connectWS(roomId);
    return () => {
      cancelled = true;
      disconnectWS();
    };
  }, [roomId]);

  // /app never scrolls; the landing must. Driven by an attribute so the rules
  // live in CSS (see index.css) rather than as inline styles that fight each
  // other across the route change.
  useEffect(() => {
    document.documentElement.dataset.route = route;
  }, [route]);

  return (
    <div className="relative h-full w-full">
      {/* Mounted once, never unmounted — this is what makes the hand-off
          seamless. Fixed, behind everything, full viewport in both routes. */}
      <div className="fixed inset-0 z-0">
        <SceneRoot landing={landing} />
      </div>

      {landing ? (
        <Suspense fallback={null}>
          <Landing onEnter={() => navigate("app")} />
        </Suspense>
      ) : (
        // pointer-events-none is load-bearing, not tidiness. This layer covers
        // the whole viewport above the Canvas, so with the default
        // pointer-events:auto it swallows every wheel and drag before
        // OrbitControls can see one - the 3D view cannot be orbited or zoomed
        // at all, and a trackpad pinch falls through to the browser and zooms
        // the entire page instead. WorldDashboard's own root already disables
        // pointer events and each panel re-enables them for itself, so this
        // simply stops the wrapper from undoing that.
        <div className="pointer-events-none relative z-10 h-full w-full">
          <WorldDashboard onBack={() => navigate("landing")} />
        </div>
      )}
    </div>
  );
}
