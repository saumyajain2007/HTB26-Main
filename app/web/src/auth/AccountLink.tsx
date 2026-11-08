import { useAuth0 } from "@auth0/auth0-react";
import { Link, useLocation } from "react-router";
import { copy } from "../copy/en";
import styles from "./Auth.module.css";

export function AccountLink() {
  const { isLoading, isAuthenticated } = useAuth0();
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}${location.hash}`;
  if (isLoading) {
    return <span className={styles.accountLink}>{copy.auth.checking}</span>;
  }
  return (
    <Link
      className={styles.accountLink}
      to={isAuthenticated ? "/account" : `/login?returnTo=${encodeURIComponent(returnTo)}`}
    >
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
        <circle cx="12" cy="8" r="3.5" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 21v-2a7 7 0 0 1 14 0v2" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      {isAuthenticated ? copy.auth.account : copy.auth.signIn}
    </Link>
  );
}
