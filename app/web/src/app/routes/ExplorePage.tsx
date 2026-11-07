import { DiseaseSearch } from "../../steps/DiseaseSearch";
import { FigureGrid } from "../Figure";
import { Shell } from "../Shell";

/**
 * `/explore`: step 1 before any Experiment is on screen. It opens the first common Disease at
 * once, so its network shows straight away and Next can carry on; the reader can choose another.
 */
export function ExplorePage() {
  return (
    <Shell step="disease">
      <FigureGrid layout="search">
        <DiseaseSearch preload />
      </FigureGrid>
    </Shell>
  );
}
