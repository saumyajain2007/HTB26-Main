import { type RouteObject } from "react-router";
import { AccountPage } from "../auth/AccountPage";
import { LoginPage } from "../auth/LoginPage";
import { diseaseFlowEnabled } from "./flags";
import { EvaluationPage } from "./routes/EvaluationPage";
import { ExperimentLayout } from "./routes/ExperimentLayout";
import { ExplorePage } from "./routes/ExplorePage";
import { IntroPage } from "./routes/IntroPage";
import { NotFoundPage } from "./routes/NotFoundPage";
import { PathogenPage } from "./routes/PathogenPage";
import { ResistanceLayout } from "./routes/ResistanceLayout";
import { ResistanceStep } from "./routes/ResistanceStep";
import { RouteErrorPage } from "./routes/RouteErrorPage";
import { StepFigure } from "./routes/StepFigure";
import { EXPLORE_PATH, RESISTANCE_PATH } from "./steps";

/**
 * The COVID-19 disease flow of plan.md: the disease search, an Experiment's eight steps and the
 * ranking evaluation. Mounted only while `diseaseFlowEnabled` (issue #32), so by default these
 * addresses are not found and the app has one flow, the antibiotic one.
 */
const diseaseFlowRoutes: RouteObject[] = [
  { path: EXPLORE_PATH, element: <ExplorePage /> },
  {
    // The layout loads the Experiment and holds the persistent network; the step adds panels.
    path: "e/:experimentId",
    element: <ExperimentLayout />,
    children: [{ path: ":step", element: <StepFigure /> }],
  },
  { path: "evaluation", element: <EvaluationPage /> },
];

/**
 * The antibiotic resistance flow. Always mounted, including while the disease flow is on, so the
 * two can be worked on and tested side by side.
 */
const resistanceFlowRoutes: RouteObject[] = [
  { path: RESISTANCE_PATH, element: <PathogenPage /> },
  {
    // The layout loads the profile and its candidates; the step adds panels.
    path: `${RESISTANCE_PATH}/:profileId`,
    element: <ResistanceLayout />,
    children: [{ path: ":step", element: <ResistanceStep /> }],
  },
];

/** Every address the app answers, with the disease flow's own mounted only when `diseaseFlow`. */
export function createRoutes(diseaseFlow: boolean): RouteObject[] {
  return [
    {
      errorElement: <RouteErrorPage />,
      children: [
        { path: "login", element: <LoginPage /> },
        { path: "account", element: <AccountPage /> },
        {
          // `/` is the introduction whether or not the disease flow is on: the problem, the
          // approach, the three pathogens, and the way into the resistance flow.
          index: true,
          element: <IntroPage />,
        },
        ...(diseaseFlow ? diseaseFlowRoutes : []),
        ...resistanceFlowRoutes,
        { path: "*", element: <NotFoundPage /> },
      ],
    },
  ];
}

export const routes: RouteObject[] = createRoutes(diseaseFlowEnabled);
