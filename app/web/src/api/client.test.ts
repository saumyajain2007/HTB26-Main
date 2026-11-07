import { describe, expect, it, vi } from "vitest";
import { sessionFetch } from "./client";

describe("anonymous session bootstrap", () => {
  it("waits for the first cookie-setting response before sending concurrent requests", async () => {
    let complete!: (response: Response) => void;
    const first = new Promise<Response>((resolve) => {
      complete = resolve;
    });
    const fetcher = vi.fn<typeof fetch>().mockReturnValueOnce(first);
    fetcher.mockResolvedValue(new Response());
    const fetch = sessionFetch(fetcher);
    const common = fetch("/api/diseases/common");
    const history = fetch("/api/experiments");
    expect(fetcher).toHaveBeenCalledTimes(1);
    complete(new Response());
    await Promise.all([common, history]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("allows a fresh bootstrap after a network failure", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValueOnce(new TypeError("offline"));
    fetcher.mockResolvedValue(new Response());
    const fetch = sessionFetch(fetcher);
    await expect(fetch("/api/diseases/common")).rejects.toThrow("offline");
    await expect(fetch("/api/diseases/common")).resolves.toBeInstanceOf(Response);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
