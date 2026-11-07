import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../../copy/en";
import { renderApp } from "../../test/render";
import { EXPLORE_PATH } from "../steps";

describe("IntroPage", () => {
  it("introduces the approach and leads into the app", () => {
    renderApp("/");

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.intro.title);
    expect(screen.getByRole("link", { name: copy.intro.start })).toHaveAttribute(
      "href",
      EXPLORE_PATH,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: copy.intro.workflow.title }),
    ).toBeInTheDocument();
  });

  it("names the four steps of the method", () => {
    renderApp("/");

    for (const step of copy.intro.method) {
      expect(screen.getByRole("heading", { level: 2, name: step.title })).toBeInTheDocument();
    }
  });
});
