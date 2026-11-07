import { copy } from "../../copy/en";
import { MessagePage } from "./MessagePage";

export function NotFoundPage() {
  return <MessagePage {...copy.notFound} />;
}
