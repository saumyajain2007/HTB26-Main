import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

function renderWithVerdict(outcome: "binds" | "does_not_bind") {
  const files = redockControl().files;
  if (files === null) throw new Error("The redock fixture requires pose files.");
  const client = new QueryClient();
  for (const file of [files.receptor, files.poses, files.crystal_ligand]) {
    client.setQueryData(dockFileQuery(file).queryKey, "fixture");
  }
  return render(
    <QueryClientProvider client={client}>
      <PoseViewer
        files={files}
        label="Binding pose"
        verdict={{ outcome, basis: "Docking score −8.0 against a threshold of −7.0." }}
      />
    </QueryClientProvider>,
  );
}

it.each([
  ["binds", "Predicted to bind"],
  ["does_not_bind", "Predicted not to bind"],
] as const)("shows the %s verdict only once the drug has arrived", (outcome, text) => {
  let arrive: () => void = () => undefined;
  const play = vi.spyOn(PoseScene.prototype, "playDock").mockImplementation((_verdict, options) => {
    arrive = () => options?.onDone?.();
  });
  renderWithVerdict(outcome);
  expect(play).toHaveBeenCalledWith(outcome, expect.anything());
  expect(screen.queryByText(text)).not.toBeInTheDocument();
  act(arrive);
  expect(screen.getByRole("status")).toHaveTextContent(text);
  expect(screen.getByRole("status")).toHaveTextContent("threshold of −7.0");
  play.mockRestore();
});

it("offers a replay only when there is a verdict, and replays on press", async () => {
  const play = vi.spyOn(PoseScene.prototype, "playDock").mockImplementation(() => undefined);
  renderWithVerdict("binds");
  expect(play).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Replay binding" }));
  expect(play).toHaveBeenCalledTimes(2);
  play.mockRestore();
});
