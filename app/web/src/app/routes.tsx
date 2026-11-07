import type { RouteObject } from "react-router";
import { EvaluationPage } from "./routes/EvaluationPage";
import { ExperimentLayout } from "./routes/ExperimentLayout";
import { ExplorePage } from "./routes/ExplorePage";
import { IntroPage } from "./routes/IntroPage";
import { NotFoundPage } from "./routes/NotFoundPage";
import { RouteErrorPage } from "./routes/RouteErrorPage";
import { StepFigure } from "./routes/StepFigure";
import { EXPLORE_PATH } from "./steps";

export const routes: RouteObject[] = [
  {
    errorElement: <RouteErrorPage />,
    children: [
      // The introduction: the problem and the approach, then the way into the steps.
      { index: true, element: <IntroPage /> },
      { path: EXPLORE_PATH, element: <ExplorePage /> },
      {
        // The layout loads the Experiment and holds the persistent network; the step adds panels.
        path: "e/:experimentId",
        element: <ExperimentLayout />,
        children: [{ path: ":step", element: <StepFigure /> }],
      },
      { path: "evaluation", element: <EvaluationPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
