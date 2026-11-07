import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/errors";
import { createQueryClient } from "../app/queryClient";
import {
  PRESET_WITHOUT_PROFILE,
  PRESET_WITH_PROFILE,
  PROFILE_ID,
  UNKNOWN_PROFILE_ID,
} from "../test/resistance";
import {
  hasProfile,
  useAntibioticCandidates,
  useCertificates,
  usePathogenPresets,
  useResistanceProfile,
  useResistanceProfiles,
} from "./resistance";

/** A fresh cache per hook, with no retries, so a failure shows at once. */
function renderQuery<T>(hook: () => T) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({
    queries: { ...queryClient.getDefaultOptions().queries, retry: false },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(hook, { wrapper });
}

describe("usePathogenPresets", () => {
  it("offers the three pathogens, with a profile only for the one that has one", async () => {
    const { result } = renderQuery(() => usePathogenPresets());
    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    const presets = result.current.data ?? [];
    expect(presets.map((preset) => preset.id)).toEqual([
      PRESET_WITH_PROFILE,
      PRESET_WITHOUT_PROFILE,
      "a_baumannii_carbapenem",
    ]);
    expect(presets.filter(hasProfile).map((preset) => preset.profile_id)).toEqual([PROFILE_ID]);
  });

  it("says why a pathogen has no profile instead of leaving it blank", async () => {
    const { result } = renderQuery(() => usePathogenPresets());
    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    const without = result.current.data?.find((preset) => preset.id === PRESET_WITHOUT_PROFILE);
    expect(without?.profile_id).toBeNull();
    expect(without?.note).toBe("No profile built for this pathogen yet.");
  });
});

describe("useResistanceProfile", () => {
  it("loads the S. aureus profile with its determinants and defeated classes", async () => {
    const { result } = renderQuery(() => useResistanceProfile(PROFILE_ID));
    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    const profile = result.current.data;
    expect(profile?.profile_id).toBe(PROFILE_ID);
    expect(profile?.input.species.name).toBe("Staphylococcus aureus");
    expect(profile?.genes.map((gene) => gene.aro_id)).toContain("ARO:3000617");
    // Reported, never silently dropped.
    expect(profile?.unresolved_inputs.map((input) => input.text)).toEqual(["blaZZ"]);
    expect(profile?.caveats.length).toBeGreaterThan(0);
  });

  it("asks nothing while there is no profile to ask about", () => {
    const { result } = renderQuery(() => useResistanceProfile(undefined));
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
  });

  it("fails with the API's own 404 for a profile that doesn't exist", async () => {
    const { result } = renderQuery(() => useResistanceProfile(UNKNOWN_PROFILE_ID));
    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(ApiError);
    });
    expect((result.current.error as ApiError | null)?.status).toBe(404);
  });

  it("lists every profile the API holds", async () => {
    const { result } = renderQuery(() => useResistanceProfiles());
    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });
    expect(result.current.data?.map((profile) => profile.profile_id)).toEqual([PROFILE_ID]);
  });
});

describe("useAntibioticCandidates", () => {
  it("loads the ranked candidates, and says the fixture numbers are made up", async () => {
    const { result } = renderQuery(() => useAntibioticCandidates(PROFILE_ID));
    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    const data = result.current.data;
    expect(data?.profile_id).toBe(PROFILE_ID);
    // Approved drugs are ranked 1..n; a generated proposal is never ranked with them.
    expect(data?.candidates.filter((c) => c.source === "approved").map((c) => c.rank)).toEqual([
      1, 2, 3,
    ]);
    expect(data?.candidates.filter((c) => c.source === "generated").map((c) => c.rank)).toEqual([
      null,
    ]);
    expect(data?.fixture_note).toMatch(/made up/);
  });

  it("asks nothing while there is no profile to rank against", () => {
    const { result } = renderQuery(() => useAntibioticCandidates(undefined));
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useCertificates", () => {
  it("loads every certificate, including the ones that failed or never ran", async () => {
    const { result } = renderQuery(() => useCertificates());
    await waitFor(() => {
      expect(result.current.data).toBeDefined();
    });

    const certificates = result.current.data ?? [];
    expect(certificates.length).toBeGreaterThan(1);
    expect(certificates.some((certificate) => certificate.certified)).toBe(true);
    expect(certificates.some((certificate) => !certificate.ran)).toBe(true);
    // Never certified without having run.
    expect(certificates.every((c) => !c.certified || c.ran)).toBe(true);
  });
});
