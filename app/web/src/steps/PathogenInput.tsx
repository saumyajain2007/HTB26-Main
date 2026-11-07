import { useId, useMemo, useState } from "react";
import { Panel } from "../app/Figure";
import { copy } from "../copy/en";
import { parseGeneList } from "../lib/pathogenInput";
import { hasProfile, usePathogenPresets, type ResistanceProfile } from "../lib/resistance";
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
 * TODO(#15): the typed list is split and tidied here, and goes nowhere. Resolving a name against
 * CARD needs the resistance profiling endpoint of issue #15, so this component cannot tell a
 * known name from an unknown one and must not pretend to. Once that endpoint lands, this needs
 * only a mutation that posts `parsed.entries` and hands the new profile's ID to `onProfile`,
 * which is the same way a preset opens.
 */
export function PathogenInput({ profile, onProfile }: PathogenInputProps) {
  const presets = usePathogenPresets();
  const [typed, setTyped] = useState("");
  const parsed = useMemo(() => parseGeneList(typed), [typed]);
  const presetsTitleId = useId();
  const genesFieldId = useId();
  const genesHintId = useId();
  const genesBlockedId = useId();
  const profileTitleId = useId();
  const noteId = useId();

  const pathogen = copy.resistance.pathogen;
  const items = presets.data ?? [];

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
            aria-describedby={`${genesHintId} ${genesBlockedId}`}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
          />
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
          <p id={genesBlockedId} className={styles.blocked}>
            {pathogen.genesBlocked}
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
