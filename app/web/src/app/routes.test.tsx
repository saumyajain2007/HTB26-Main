import { screen } from "@testing-library/react";
import { isValidElement, type ReactNode } from "react";
import type { RouteObject } from "react-router";
import { describe, expect, it } from "vitest";
import { copy } from "../copy/en";
import { renderApp } from "../test/render";
import { diseaseFlowEnabled } from "./flags";
import { createRoutes } from "./routes";
import { EXPLORE_PATH, RESISTANCE_PATH } from "./steps";

/** The addresses the app answers, under the one error-element parent. */
function childrenOf(routes: RouteObject[]): RouteObject[] {
  return routes[0]?.children ?? [];
}

function pathsOf(routes: RouteObject[]): (string | undefined)[] {
  return childrenOf(routes).map((route) => route.path);
}

/** Where a `<Navigate>` element sends the reader, or undefined when it isn't one. */
function navigatesTo(element: ReactNode): string | undefined {
  if (!isValidElement<{ to?: unknown }>(element)) return undefined;
  return typeof element.props.to === "string" ? element.props.to : undefined;
}

describe("the disease flow's gate", () => {
  it("is on for this suite, so the old flow's tests keep exercising the old flow", () => {
    expect(diseaseFlowEnabled).toBe(true);
  });

  it("gives the disease flow its addresses while it is on", () => {
    const paths = pathsOf(createRoutes(true));
    expect(paths).toContain(EXPLORE_PATH);
    expect(paths).toContain("e/:experimentId");
    expect(paths).toContain("evaluation");
  });

  it("leaves the disease flow without addresses while it is off", () => {
    const paths = pathsOf(createRoutes(false));
    expect(paths).not.toContain(EXPLORE_PATH);
    expect(paths).not.toContain("e/:experimentId");
    expect(paths).not.toContain("evaluation");
    // Anything the flow used to answer falls through to the catch-all.
    expect(paths).toContain("*");
  });

  it("sends `/` to the resistance flow while the disease flow is off, and not while it is on", () => {
    const index = (routes: RouteObject[]) =>
      childrenOf(routes).find((route) => route.index === true);
    expect(navigatesTo(index(createRoutes(false))?.element)).toBe(RESISTANCE_PATH);
    expect(navigatesTo(index(createRoutes(true))?.element)).toBeUndefined();
  });

  it("mounts the resistance flow either way", () => {
    for (const diseaseFlow of [true, false]) {
      const paths = pathsOf(createRoutes(diseaseFlow));
      expect(paths).toContain(RESISTANCE_PATH);
      expect(paths).toContain(`${RESISTANCE_PATH}/:profileId`);
    }
  });

  it("runs the resistance flow on its own while the disease flow is off", async () => {
    const offRoutes = createRoutes(false);
    renderApp("/", offRoutes);
    expect(
      await screen.findByRole("heading", { level: 1, name: copy.resistanceSteps[0].title }),
    ).toBeInTheDocument();
  });

  it("does not answer the disease flow's addresses while it is off", () => {
    renderApp(EXPLORE_PATH, createRoutes(false));
    expect(
      screen.getByRole("heading", { level: 1, name: copy.notFound.title }),
    ).toBeInTheDocument();
  });
});
