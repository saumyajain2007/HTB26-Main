import { describe, expect, it } from "vitest";
import { polarContacts, residueName } from "./interactions";

const drugO = { x: 0, y: 0, z: 0, elem: "O", atom: "O3" };
const drugC = { x: 0, y: 0, z: 0, elem: "C", atom: "C1" };

describe("residueName", () => {
  it("writes a three-letter code in title case with its number", () => {
    expect(residueName("ASP", 73)).toBe("Asp73");
    expect(residueName(undefined, undefined)).toBe("");
  });
});

describe("polarContacts", () => {
  it("finds N and O pairs within 3.5 Å, closest first", () => {
    const protein = [
      { x: 3.4, y: 0, z: 0, elem: "N", atom: "NE2", resn: "GLN", resi: 9, chain: "A" },
      { x: 2.9, y: 0, z: 0, elem: "O", atom: "OD1", resn: "ASP", resi: 73, chain: "A" },
      { x: 3.6, y: 0, z: 0, elem: "N", atom: "N", resn: "GLY", resi: 5, chain: "A" },
    ];
    const contacts = polarContacts([drugO], protein);
    expect(contacts.map((c) => c.residue)).toEqual(["Asp73", "Gln9"]);
    expect(contacts[0]?.distance).toBeCloseTo(2.9);
    expect(contacts[0]).toMatchObject({ ligandAtom: "O3", proteinAtom: "OD1", chain: "A" });
  });

  it("ignores carbon, water and anything out of reach", () => {
    const protein = [
      { x: 3, y: 0, z: 0, elem: "C", atom: "CB", resn: "ALA", resi: 1 },
      { x: 2.8, y: 0, z: 0, elem: "O", atom: "O", resn: "HOH", resi: 301 },
      { x: 8, y: 0, z: 0, elem: "N", atom: "N", resn: "SER", resi: 2 },
    ];
    expect(polarContacts([drugO], protein)).toEqual([]);
    expect(
      polarContacts([drugC], [{ x: 2.9, y: 0, z: 0, elem: "O", resn: "ASP", resi: 3 }]),
    ).toEqual([]);
  });
});
