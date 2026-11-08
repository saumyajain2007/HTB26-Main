import { useId, useMemo, useState } from "react";
import { Panel } from "../app/Figure";
import { copy } from "../copy/en";
import { parseGeneList } from "../lib/pathogenInput";
import { ApiError } from "../api/errors";
import {
  hasProfile,
  useBuildProfile,
  usePathogenPresets,
  type ResistanceProfile,
} from "../lib/resistance";
import styles from "./PathogenInput.module.css";

export interface PathogenInputProps {
  /**
   * The profile already on screen, when the reader comes back to step 1 from the map. Undefined
   * on `/resistance`, before anything has been profiled.
   */
  profile?: ResistanceProfile | undefined;
  /**
   * Called with the ID of the profile to open, once the reader picks a preset that has one or a
   * pasted gene list has been profiled. The page navigates; this component never does.
   */
  onProfile: (profileId: string) => void;
}

/**
 * Step 1 of the resistance flow: pick one of the pathogens, or type the resistance genes an
 * isolate carries. Draws its own `Panel` into the page's figure grid.
 *
 * A pathogen the API has no profile for is offered all the same, kept out of use and carrying
 * the API's own note, so a reader sees it exists and why it cannot be opened.
 *
 * The typed list is split and tidied here, but never judged: resolving a name against CARD needs
 * the server's vocabulary, so the names that matched nothing come back from
 * `POST /api/resistance/profiles` with CARD's own reason. A profile built from typed names opens
 * the same way a preset does, through `onProfile`.
 */
export function PathogenInput({ profile, onProfile }: PathogenInputProps) {
  const presets = usePathogenPresets();
  const [typed, setTyped] = useState("");
  const parsed = useMemo(() => parseGeneList(typed), [typed]);
  const presetsTitleId = useId();
  const genesFieldId = useId();
  const genesHintId = useId();
  const genesStatusId = useId();
  const profileTitleId = useId();
  const noteId = useId();

  const pathogen = copy.resistance.pathogen;
  const items = presets.data ?? [];
  const build = useBuildProfile();

  // A 503 means the server has no CARD release, so nothing was looked up: say that, rather than
  // letting a reader think a name of theirs was rejected.
  const failure = build.error;
  const buildMessage =
    failure === null
      ? null
      : failure instanceof ApiError && failure.status === 503
        ? pathogen.genesUnavailable
        : failure instanceof ApiError && failure.status === 422 && failure.detail !== null
          ? pathogen.genesRefused(failure.detail)
          : pathogen.genesFailed;

  function submit() {
    build.mutate(
      { kind: "gene_list", genes: parsed.entries.join(", ") },
      {
        onSuccess: (profile) => {
          onProfile(profile.profile_id);
        },
      },
    );
  }

  return (
    <Panel area="main">
      <div className={styles.columns}>
        <section className={styles.column} aria-labelledby={presetsTitleId}>
          <h2 id={presetsTitleId} className={styles.heading}>
            {pathogen.presetsTitle}
          </h2>
          <ul className={styles.presets}>
            {items.map((preset) => {
              const openable = hasProfile(preset);
              const current = preset.profile_id === profile?.profile_id;
              const presetNoteId = `${noteId}-${preset.id}`;
              return (
                <li key={preset.id} className={styles.item}>
                  <button
                    type="button"
                    className={styles.preset}
                    aria-current={current ? "true" : undefined}
                    aria-disabled={openable ? undefined : "true"}
                    aria-describedby={preset.note === null ? undefined : presetNoteId}
                    onClick={() => {
                      if (hasProfile(preset)) onProfile(preset.profile_id);
                    }}
                  >
                    <span className={styles.label}>{preset.label}</span>
                  </button>
                  {/* Outside the button, so the pathogen's name stays its own and the note
                      describes it. */}
                  {preset.note !== null && (
                    <p id={presetNoteId} className={styles.note}>
                      {preset.note}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
          {presets.isPending && (
            <p className={styles.status} role="status">
              {pathogen.presetsLoading}
            </p>
          )}
          {presets.isError && (
            <div className={styles.status} role="status">
              <p>{pathogen.presetsUnavailable}</p>
              <button type="button" className={styles.retry} onClick={() => void presets.refetch()}>
                {copy.retry}
              </button>
            </div>
          )}
        </section>

        {/* The label names the field, and only the field: a section labelled by it as well
            would answer to the same name twice. */}
        <section className={styles.column}>
          <label className={styles.heading} htmlFor={genesFieldId}>
            {pathogen.genesLabel}
          </label>
          <p id={genesHintId} className={styles.hint}>
            {pathogen.genesHint}
          </p>
          <textarea
            id={genesFieldId}
            className={styles.field}
            value={typed}
            rows={5}
            spellCheck={false}
            aria-describedby={genesHintId}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
          />
          {/* Shapes of a name, not suggestions: the server alone says which ones CARD knows. */}
          <div className={styles.examples}>
            <span className={styles.examplesLabel}>{pathogen.genesExamplesLabel}</span>
            {pathogen.genesExamples.map((example) => (
              <button
                key={example}
                type="button"
                className={styles.example}
                onClick={() => {
                  setTyped((current) =>
                    current.trim() === "" ? example : `${current.trimEnd()}\n${example}`,
                  );
                }}
              >
                {example}
              </button>
            ))}
          </div>
          {typed.trim() !== "" && (
            <div className={styles.parsed}>
              <p className={styles.count}>{pathogen.genesRead(parsed.entries.length)}</p>
              <ul className={styles.entries}>
                {parsed.entries.map((entry) => (
                  <li key={entry} className={styles.entry}>
                    {entry}
                  </li>
                ))}
              </ul>
              {parsed.repeated.length > 0 && (
                <p className={styles.note}>{pathogen.genesRepeated(parsed.repeated)}</p>
              )}
            </div>
          )}
          <button
            type="button"
            className={styles.submit}
            disabled={parsed.entries.length === 0 || build.isPending}
            onClick={submit}
          >
            {pathogen.genesSubmit}
          </button>
          {/* One live region for both the wait and the failure, so a screen reader hears each
              once and in the order they happen. */}
          <p id={genesStatusId} className={styles.blocked} role="status">
            {build.isPending ? pathogen.genesBuilding : (buildMessage ?? "")}
          </p>
        </section>
      </div>

      {profile !== undefined && (
        <section className={styles.current} aria-labelledby={profileTitleId}>
          <h2 id={profileTitleId} className={styles.heading}>
            {pathogen.profileTitle}
          </h2>
          {/* The pathogen is named here, not in the header, on the step that chooses it. */}
          <p className={styles.species}>{profile.input.species.name}</p>
          <p className={styles.hint}>
            {pathogen.profileResolved(profile.genes.length, profile.input.requested.length)}
          </p>
          {profile.unresolved_inputs.length > 0 && (
            <>
              <p className={styles.count}>{pathogen.profileUnresolved}</p>
              <ul className={styles.unresolved}>
                {profile.unresolved_inputs.map((unresolved) => (
                  <li key={unresolved.text}>
                    <span className={styles.entry}>{unresolved.text}</span>
                    <span className={styles.note}>{unresolved.reason}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </Panel>
  );
}
