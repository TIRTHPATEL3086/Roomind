import { useCallback, useEffect, useState } from "react";

export type Route = "landing" | "app";

/**
 * Two-route history routing, no router dependency.
 *
 * RoomMind has exactly two views and the Canvas lives above both of them, so a
 * routing library would add a dependency and a re-render boundary for no gain.
 *
 * `/app` must resolve standalone — it is the bookmark used to open the pitch,
 * and the one URL that has to work if the cinematic misbehaves (spec 13.12).
 */
export function useRoute(): [Route, (r: Route) => void] {
  const read = (): Route =>
    typeof window !== "undefined" && window.location.pathname.startsWith("/app")
      ? "app"
      : "landing";

  const [route, setRoute] = useState<Route>(read);

  useEffect(() => {
    const onPop = () => setRoute(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((r: Route) => {
    const path = r === "app" ? "/app" : "/";
    if (window.location.pathname !== path) {
      // Preserve ?nomotion=1 across the hand-off so the flag survives.
      window.history.pushState({}, "", path + window.location.search);
    }
    setRoute(r);
  }, []);

  return [route, navigate];
}
