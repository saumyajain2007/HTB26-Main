import { HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { http, server } from "../test/server";
import { PoseScene } from "../three/poseScene";
import { BoltzPanel } from "./BoltzPanel";

function show() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <BoltzPanel
        profileId="00000000-0000-4000-8000-000000000001"
        candidateId="CHEMBL1"
        candidateName="Test molecule"
      />
    </QueryClientProvider>,
  );
}

it("distinguishes absent predictions from reference structures", async () => {
  show();
  expect(await screen.findByText(/No Boltz prediction has been prepared/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Show Boltz prediction" })).not.toBeInTheDocument();
});

it("renders Boltz PDB coordinates with confidence and without a crystal overlay", async () => {
  server.use(
    http.get(
      "/api/resistance/profiles/{profile_id}/candidates/{candidate_id}/boltz",
      ({ response }) =>
        response(200).json({
          profile_id: "00000000-0000-4000-8000-000000000001",
          candidate_id: "CHEMBL1",
          smiles: "C",
          target_name: "Pathogen protein",
          boltz_version: "2.2.1",
          protein_sequence_sha256: "a".repeat(64),
          confidence_score: 0.88,
          receptor: {
            url: "/api/resistance/profiles/00000000-0000-4000-8000-000000000001/candidates/CHEMBL1/boltz/receptor.pdb",
            sha256: "a".repeat(64),
          },
          ligand: {
            url: "/api/resistance/profiles/00000000-0000-4000-8000-000000000001/candidates/CHEMBL1/boltz/ligand.pdb",
            sha256: "b".repeat(64),
          },
        }),
    ),
    http.get("/api/resistance/profiles/{profile_id}/candidates/{candidate_id}/boltz/{name}", () =>
      HttpResponse.text("PDB coordinates"),
    ),
  );
  const create = vi.spyOn(PoseScene, "create");
  const play = vi.spyOn(PoseScene.prototype, "playPlacement");
  show();
  expect(await screen.findByText(/Model confidence: 0.880/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Show Boltz prediction" }));
  await waitFor(() => {
    expect(screen.getByRole("img", { name: /predicted by Boltz-2/ })).toHaveAttribute(
      "data-ready",
      "true",
    );
  });
  await waitFor(() => {
    expect(play).toHaveBeenCalledTimes(1);
  });
  expect(create.mock.calls.at(-1)?.[2]).toMatchObject({
    receptor: "PDB coordinates",
    poses: "PDB coordinates",
    posesFormat: "pdb",
  });
  expect(screen.queryByRole("button", { name: /crystal/i })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Hide Boltz prediction" }));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Show Boltz prediction" }));
  await waitFor(() => {
    expect(play).toHaveBeenCalledTimes(2);
  });
});
