import { useEffect, useState } from "react";

import { PHONE_BREAKPOINT } from "../designer/phone";

const QUERY = `(max-width: ${PHONE_BREAKPOINT - 0.02}px)`;

/** True while the window is narrower than the phone breakpoint (768 px); follows resizes and rotation. */
export function useNarrowWindow(): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia(QUERY).matches);
  useEffect(() => {
    const media = window.matchMedia(QUERY);
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return narrow;
}
