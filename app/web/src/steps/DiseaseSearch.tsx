import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router";
import { useCommonDiseases, useDiseaseSearch, useOpenDisease } from "../api/queries";
import type { Experiment } from "../api/types";
import { Panel } from "../app/Figure";
import { EXPLORE_PATH, stepPath } from "../app/steps";
import { copy } from "../copy/en";
import styles from "./DiseaseSearch.module.css";

/**
 * Underlines the part of `text` that matches the query, case-insensitively. A whole-text match
 * stays plain: underlining all of it would only make it look like a link.
 */
function marked(text: string, query: string): ReactNode {
  const at = query === "" ? -1 : text.toLowerCase().indexOf(query.toLowerCase());
  if (at < 0 || query.length === text.length) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark>{text.slice(at, at + query.length)}</mark>
      {text.slice(at + query.length)}
    </>
  );
}

/** One Disease to choose: a search result, or a common Disease before anything is typed. */
interface Option {
  id: string;
  name: string;
  matched_synonym: string | null;
}

interface DiseaseSearchProps {
  /** The Experiment on screen, if any: its Disease is pre-filled and marked as current. */
  current?: Experiment | undefined;
  /** Open the first common Disease straight away, in place of this page (the landing page). */
  preload?: boolean;
}

/**
 * Step 1: choose a Disease. Until something is typed the list holds well-known Diseases (the
 * current one marked); typing searches every Disease instead. Choosing one stays on this step and
 * shows its network: a saved Experiment for it when there is one, else a new one as it builds.
 * Next then carries on with whichever Disease is shown. The search stays mounted while the
 * Disease on screen changes, so the list, its scroll and focus stay put and only the mark moves.
 */
export function DiseaseSearch({ current, preload = false }: DiseaseSearchProps) {
  const name = current?.disease.name ?? "";
  const [query, setQuery] = useState(name);
  // The box holds the Disease on screen: when another one comes on screen, the box follows it.
  const [shown, setShown] = useState(name);
  if (shown !== name) {
    setShown(name);
    setQuery(name);
  }
  const searching = query.trim() !== "" && query !== current?.disease.name;
  const search = useDiseaseSearch(searching ? query : "");
  const common = useCommonDiseases();
  const open = useOpenDisease();
  const navigate = useNavigate();
  const [navigating, startNavigation] = useTransition();
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);

  const results: Option[] = searching
    ? (search.data?.results ?? [])
    : (common.data ?? []).map((disease) => ({ ...disease, matched_synonym: null }));
  const marking = searching ? query.trim() : "";

  const { mutate } = open;
  // The chosen Disease stays busy until its screen is drawn, not just until it is opened.
  const opening = open.isPending || navigating ? open.variables : undefined;
  const show = useCallback(
    (experimentId: string, replace: boolean) => {
      startNavigation(async () => {
        await navigate(stepPath(experimentId, "disease") ?? EXPLORE_PATH, { replace });
      });
    },
    [navigate],
  );
  const choose = (diseaseId: string) => {
    if (current?.disease.id === diseaseId) return;
    // A mutation's own callbacks never run once this page has gone, so a choice made while
    // the first common Disease is still opening wins.
    mutate(diseaseId, {
      onSuccess: (experimentId) => {
        show(experimentId, false);
      },
    });
  };

  const first = common.data?.[0]?.id;
  const preloaded = useRef(false);
  useEffect(() => {
    if (!preload || first === undefined || preloaded.current) return;
    preloaded.current = true;
    mutate(first, {
      onSuccess: (experimentId) => {
        show(experimentId, true);
      },
    });
  }, [preload, first, mutate, show]);

  const options = () => [...(listRef.current?.querySelectorAll("button") ?? [])];

  const onInputKey = (event: KeyboardEvent<HTMLInputElement>) => {
    const first = results[0];
    if (event.key === "Enter" && first !== undefined) {
      event.preventDefault();
      choose(first.id);
    } else if (event.key === "ArrowDown" && first !== undefined) {
      event.preventDefault();
      options()[0]?.focus();
    }
  };

  const onListKey = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const buttons = options();
    const at = buttons.findIndex((button) => button === document.activeElement);
    const next = at + (event.key === "ArrowDown" ? 1 : -1);
    if (next < 0) listRef.current?.parentElement?.querySelector("input")?.focus();
    else buttons[Math.min(next, buttons.length - 1)]?.focus();
  };

  let status: ReactNode = null;
  if (open.isError) {
    const retryId = open.variables;
    status = (
      <>
        <p>{copy.search.createFailed}</p>
        <button
          type="button"
          className={styles.retry}
          onClick={() => {
            choose(retryId);
          }}
        >
          {copy.retry}
        </button>
      </>
    );
  } else if (searching && search.isError && search.data === undefined) {
    status = (
      <>
        <p>{copy.search.unavailable}</p>
        <button type="button" className={styles.retry} onClick={() => void search.refetch()}>
          {copy.retry}
        </button>
      </>
    );
  } else if (searching && search.settled && search.isSuccess && results.length === 0) {
    status = <p>{copy.search.noMatch(query.trim())}</p>;
  }

  return (
    <Panel area="search" label={copy.search.placeholder}>
      <div className={styles.search}>
        <input
          type="search"
          className={styles.input}
          value={query}
          placeholder={copy.search.placeholder}
          aria-label={copy.search.placeholder}
          aria-controls={listId}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => {
            setQuery(event.target.value);
            if (open.isError) open.reset();
          }}
          onKeyDown={onInputKey}
        />
        {!searching && results.length > 0 && <p className={styles.label}>{copy.search.common}</p>}
        {/* Arrow keys move between results; handled on the list, as the buttons inside it. */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
        <ul id={listId} ref={listRef} className={styles.results} onKeyDown={onListKey}>
          {results.map((result) => {
            const isCurrent = current?.disease.id === result.id;
            const busy = opening === result.id;
            return (
              <li key={result.id}>
                <button
                  type="button"
                  className={styles.option}
                  aria-current={isCurrent ? "true" : undefined}
                  aria-busy={busy || undefined}
                  disabled={opening !== undefined}
                  onClick={() => {
                    choose(result.id);
                  }}
                >
                  <span className={styles.name}>{marked(result.name, marking)}</span>
                  <span className={styles.id}>{result.id}</span>
                  {result.matched_synonym !== null && (
                    <span className={styles.synonym}>
                      {marked(result.matched_synonym, marking)}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
        {status !== null && (
          <div className={styles.status} role="status">
            {status}
          </div>
        )}
      </div>
    </Panel>
  );
}
