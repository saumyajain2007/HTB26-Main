import { lazy, Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import styles from "./ResistanceCandidates.module.css";

const PoseViewer = lazy(() =>
  import("../three/PoseViewer").then((m) => ({ default: m.PoseViewer })),
);

export function BoltzPanel({
  profileId,
  candidateId,
  candidateName,
}: {
  profileId: string;
  candidateId: string;
  candidateName: string;
}) {
  const [open, setOpen] = useState(false);
  const prediction = useQuery({
    queryKey: ["boltz", profileId, candidateId],
    queryFn: async ({ signal }) => {
      try {
        return await unwrap(
          api.GET("/api/resistance/profiles/{profile_id}/candidates/{candidate_id}/boltz", {
            params: { path: { profile_id: profileId, candidate_id: candidateId } },
            signal,
          }),
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
  const result = prediction.data;
  return (
    <div className={styles.poseCard}>
      <h4 className={styles.subhead}>
        {result?.prediction_scope === "exploratory"
          ? "Boltz-2 exploratory complex"
          : "Boltz-2 predicted complex"}
      </h4>
      {prediction.isPending && <p>Checking for a Boltz prediction…</p>}
      {prediction.isError && (
        <p role="alert">
          The Boltz prediction could not be loaded.{" "}
          <button
            type="button"
            onClick={() => {
              void prediction.refetch();
            }}
          >
            Retry
          </button>
        </p>
      )}
      {result === null && (
        <p>No Boltz prediction has been prepared for this molecule and pathogen profile.</p>
      )}
      {result !== undefined && result !== null && (
        <>
          {result.prediction_scope === "exploratory" && (
            <div>
              <p>
                <strong>Exploratory target assumption</strong>
              </p>
              <ul>
                {(result.limitations ?? []).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          <p>
            {candidateName} · {result.target_name}
          </p>
          <p>
            Model confidence: {result.confidence_score.toFixed(3)} / 1. This is a predicted complex,
            not measured binding affinity or antibiotic activity.
          </p>
          <button
            type="button"
            className={styles.poseToggle}
            aria-expanded={open}
            onClick={() => {
              setOpen(!open);
            }}
          >
            {open ? "Hide Boltz prediction" : "Show Boltz prediction"}
          </button>
          {open && (
            <p>Illustrative placement animation—not a simulated binding trajectory.</p>
          )}
          {open && (
            <div className={styles.poseStage}>
              <Suspense fallback={<p>Loading predicted complex…</p>}>
                <PoseViewer
                  predicted
                  files={{
                    receptor: result.receptor,
                    poses: result.ligand,
                    crystal_ligand: result.ligand,
                  }}
                  label={`${candidateName} with ${result.target_name}, predicted by Boltz-2. Drag to rotate.`}
                />
              </Suspense>
            </div>
          )}
        </>
      )}
    </div>
  );
}
