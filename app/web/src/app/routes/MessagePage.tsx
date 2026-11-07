import { Link } from "react-router";
import { copy } from "../../copy/en";
import { PageFrame } from "../PageFrame";
import styles from "./MessagePage.module.css";

interface MessagePageProps {
  title: string;
  body: string;
  home: string;
  /** Where `home` leads. The app's own start by default; a flow can send the reader to its own. */
  homePath?: string;
}

/** A plain page that says one thing and offers the way back to the start. */
export function MessagePage({ title, body, home, homePath = "/" }: MessagePageProps) {
  return (
    <PageFrame>
      <title>{`${title} - ${copy.product}`}</title>
      <div className={styles.body}>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.text}>{body}</p>
        <Link to={homePath} className={styles.home}>
          {home}
        </Link>
      </div>
    </PageFrame>
  );
}
