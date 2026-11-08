import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { copy } from "../../copy/en";
import { renderApp } from "../../test/render";
import { RESISTANCE_PATH } from "../steps";

describe("IntroPage", () => {
  it("introduces the approach and leads into the app", () => {
    renderApp("/");

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.intro.title);
    expect(screen.getByRole("link", { name: copy.intro.start })).toHaveAttribute(
      "href",
      RESISTANCE_PATH,
    );
    expect(
      screen.getByRole("heading", { level: 2, name: copy.intro.pathogens.title }),
    ).toBeInTheDocument();
  });

  it("names the three pathogens and leaves the old disease out", () => {
    renderApp("/");

    for (const { name } of copy.intro.pathogens.items) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toHaveAttribute(
        "href",
        RESISTANCE_PATH,
      );
    }
    expect(copy.intro.pathogens.items).toHaveLength(3);
    expect(document.body).not.toHaveTextContent(/covid|disease/i);
  });

  it("names the four steps of the method", () => {
    renderApp("/");

    for (const step of copy.intro.method) {
      expect(screen.getByRole("heading", { level: 2, name: step.title })).toBeInTheDocument();
    }
  });
});
