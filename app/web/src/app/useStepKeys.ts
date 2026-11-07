import { useEffect } from "react";

const EDITABLE = "input, textarea, select, [contenteditable]:not([contenteditable='false'])";

/**
 * ArrowUp and ArrowDown move between steps, anywhere on the page except while the user is typing
 * or a modifier key is held (so browser and assistive-technology shortcuts keep working).
 */
export function useStepKeys(onPrevious: () => void, onNext: () => void): void {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof Element && event.target.closest(EDITABLE)) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        onNext();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        onPrevious();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onPrevious, onNext]);
}
