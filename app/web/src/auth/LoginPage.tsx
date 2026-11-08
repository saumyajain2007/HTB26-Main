import { useAuth0 } from "@auth0/auth0-react";
import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { PageFrame } from "../app/PageFrame";
import { copy } from "../copy/en";
import laboratory from "../intro/assets/laboratory.webp";
import { safeReturnTo } from "./config";
import styles from "./Auth.module.css";

export function LoginPage() {
  const { isLoading, isAuthenticated, error, loginWithRedirect } = useAuth0();
  const [params] = useSearchParams();
  const returnTo = safeReturnTo(params.get("returnTo"));
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  async function signIn(signup = false) {
    setFailed(false);
    setPending(true);
    try {
      await loginWithRedirect({
        appState: { returnTo },
        ...(signup ? { authorizationParams: { screen_hint: "signup" } } : {}),
      });
    } catch {
      setFailed(true);
      setPending(false);
    }
  }

  if (!isLoading && isAuthenticated) return <Navigate to={returnTo} replace />;

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
      <title>{`${copy.auth.signIn} - ${copy.product}`}</title>
      <div className={styles.layout}>
        <section className={styles.content} aria-labelledby="login-title">
          <p className={styles.eyebrow}>{copy.auth.eyebrow}</p>
          <h1 id="login-title" className={styles.title}>
            {copy.auth.title}
          </h1>
          <p className={styles.intro}>{copy.auth.intro}</p>
          <div className={styles.actions} aria-busy={isLoading || pending}>
            {(error !== undefined || failed) && (
              <p role="alert" className={styles.error}>
                {copy.auth.loginError}
              </p>
            )}
            {isLoading && (
              <p role="status" className={styles.note}>
                {copy.auth.loading}
              </p>
            )}
            <button
              className={styles.primary}
              type="button"
              disabled={isLoading || pending}
              onClick={() => {
                void signIn();
              }}
            >
              {pending ? copy.auth.redirecting : copy.auth.signIn}
            </button>
            <button
              className={styles.secondary}
              type="button"
              disabled={isLoading || pending}
              onClick={() => {
                void signIn(true);
              }}
            >
              {copy.auth.signUp}
            </button>
            <p className={styles.note}>{copy.auth.providerNote}</p>
          </div>
          <Link className={styles.guest} to="/resistance">
            {copy.auth.guest}
          </Link>
        </section>
        <figure className={styles.illustration}>
          <img className={styles.lab} src={laboratory} alt="" />
          <figcaption className={styles.caption}>
            <p className={styles.captionTitle}>{copy.auth.figureTitle}</p>
            <p>{copy.auth.figureText}</p>
          </figcaption>
        </figure>
      </div>
    </PageFrame>
  );
}
