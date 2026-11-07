import story1 from "./assets/story-1.webp";
import story2 from "./assets/story-2.webp";
import story3 from "./assets/story-3.webp";

/*
 * What the introduction borrows from Jessica's Half Life site (Jessica-mak/half-life-ui): her
 * lab's four chapters, and details cut from her three story illustrations.
 */

export interface LabChapter {
  short: string;
  /** How long the chapter holds, in ms. */
  duration: number;
  /** The label stuck onto the lab while this chapter plays. */
  note: string;
}

export const labChapters: readonly LabChapter[] = [
  { short: "In the lab", duration: 5200, note: "One researcher. Many disconnected clues." },
  { short: "Years of testing", duration: 7200, note: "10–15 years from discovery to market" },
  { short: "Many compounds", duration: 7800, note: "Thousands screened. Few go further." },
  { short: "A different start", duration: 7200, note: "Could an existing medicine help?" },
];

/**
 * A detail of one illustration. The illustrations carry their own headlines at the left, so a
 * crop magnifies the drawing (`zoom`, as a background size) and aims at its subject (`x` `y`, as
 * a background position) to leave the lettering out.
 */
export interface StoryCrop {
  image: string;
  alt: string;
  zoom: number;
  x: number;
  y: number;
}

export const crops = {
  diseaseProtein: {
    image: story2,
    alt: "Inside a cell, a protein linked to the disease glows orange among its neighbours.",
    zoom: 230,
    x: 82,
    y: 38,
  },
  network: {
    image: story1,
    alt: "A monitor traces a path from a disease, through proteins, to an existing medicine.",
    zoom: 185,
    x: 100,
    y: 30,
  },
  review: {
    image: story3,
    alt: "Three lamps light an open evidence book: three independent AI reviews.",
    zoom: 240,
    x: 57,
    y: 20,
  },
  shortlist: {
    image: story3,
    alt: "A folder marked “Shortlist to investigate”, with medicines and a protein.",
    zoom: 330,
    x: 96,
    y: 48,
  },
} satisfies Record<string, StoryCrop>;
