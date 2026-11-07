import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { expect, it, vi } from "vitest";
import { dockFileQuery } from "../api/queries";
import { redockControl } from "../test/fixtures";
import { PoseViewer } from "./PoseViewer";
import { PoseScene } from "./poseScene";

it("releases the pose during the removal commit, before passive effects can be delayed", () => {
  const files = redockControl().files;
  if (files === null) throw new Error("The redock fixture requires pose files.");
  const poseFiles = files;
  const client = new QueryClient();
  for (const file of [files.receptor, files.poses, files.crystal_ligand]) {
    client.setQueryData(dockFileQuery(file).queryKey, "fixture");
  }
  const dispose = vi.spyOn(PoseScene.prototype, "dispose");
  let disposedDuringCommit = false;
  function Screen({ show }: { show: boolean }) {
    useLayoutEffect(() => {
      if (!show) disposedDuringCommit = dispose.mock.calls.length > 0;
    }, [show]);
    return show ? <PoseViewer files={poseFiles} label="Binding pose" /> : null;
  }
  const view = render(
    <QueryClientProvider client={client}>
      <Screen show />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("img", { name: "Binding pose" })).toHaveAttribute("data-ready", "true");
  view.rerender(
    <QueryClientProvider client={client}>
      <Screen show={false} />
    </QueryClientProvider>,
  );
  expect(disposedDuringCommit).toBe(true);
});
