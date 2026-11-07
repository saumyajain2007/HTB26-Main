let supported: boolean | undefined;

/** Whether this browser can draw WebGL at all. Checked once. */
export function canUseWebGL(): boolean {
  if (supported === undefined) {
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
      supported = gl !== null;
      // The probe's context would otherwise count against the browser's limit until collected.
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      supported = false;
    }
  }
  return supported;
}
