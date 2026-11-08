import { useAuth0 } from "@auth0/auth0-react";
import { useState } from "react";
import { Link, Navigate } from "react-router";
import { PageFrame } from "../app/PageFrame";
import { BrandMark } from "../app/BrandMark";
import { copy } from "../copy/en";
import styles from "./Auth.module.css";

export function AccountPage() {
  const { isLoading, isAuthenticated, user, logout } = useAuth0();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  async function signOut() {
    setFailed(false);
    setPending(true);
    try {
      await logout({ logoutParams: { returnTo: window.location.origin } });
    } catch {
      setFailed(true);
      setPending(false);
    }
  }

  if (!isLoading && !isAuthenticated) return <Navigate to="/login?returnTo=%2Faccount" replace />;

  return (
    <PageFrame
      flow="document"
      showAccount={false}
      header={
        <Link to="/" className={styles.accountLink}>
          {copy.auth.backHome}
        </Link>
      }
    >
      <title>{`${copy.auth.account} - ${copy.product}`}</title>
      <section className={styles.account} aria-labelledby="account-title">
        <BrandMark className={styles.mark} />
        <p className={styles.eyebrow}>{copy.auth.eyebrow}</p>
        <h1 id="account-title" className={styles.title}>
          {copy.auth.account}
        </h1>
        {isLoading ? (
          <p role="status" className={styles.intro}>
            {copy.auth.loading}
          </p>
        ) : (
          <>
            <dl className={styles.details}>
              <div>
                <dt>{copy.auth.name}</dt>
                <dd>{user?.name ?? user?.nickname ?? copy.auth.notProvided}</dd>
              </div>
              <div>
                <dt>{copy.auth.email}</dt>
                <dd>{user?.email ?? copy.auth.notProvided}</dd>
              </div>
              {user?.email && (
                <div>
                  <dt>{copy.auth.emailStatus}</dt>
                  <dd>{user.email_verified ? copy.auth.verified : copy.auth.unverified}</dd>
                </div>
              )}
            </dl>
            {failed && (
              <p role="alert" className={styles.error}>
                {copy.auth.logoutError}
              </p>
            )}
            <div className={styles.actions}>
              <Link to="/resistance" className={styles.primary}>
                {copy.auth.continue}
              </Link>
              <button
                type="button"
                className={styles.secondary}
                disabled={pending}
                onClick={() => {
                  void signOut();
                }}
              >
                {pending ? copy.auth.signingOut : copy.auth.signOut}
              </button>
            </div>
          </>
        )}
      </section>
    </PageFrame>
  );
}
