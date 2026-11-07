import { createContext, useContext } from "react";

/** What a step points at in the network while the user hovers one of its rows. */
export interface NetworkHover {
  highlight: readonly string[];
  focus: readonly string[];
}

export const NetworkHoverContext = createContext<(hover: NetworkHover | null) => void>(() => {
  // Outside an Experiment there is no network to point at.
});

/** Sets or clears the network emphasis from a step's rows. */
export function useNetworkHover(): (hover: NetworkHover | null) => void {
  return useContext(NetworkHoverContext);
}
