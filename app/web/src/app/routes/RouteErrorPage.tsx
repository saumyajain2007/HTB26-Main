import { isRouteErrorResponse, useRouteError } from "react-router";
import { copy } from "../../copy/en";
import { MessagePage } from "./MessagePage";
import { NotFoundPage } from "./NotFoundPage";

/** Shown when a route throws: a 404 response reads as not found, anything else as an error. */
export function RouteErrorPage() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) return <NotFoundPage />;
  return <MessagePage {...copy.routeError} />;
}
