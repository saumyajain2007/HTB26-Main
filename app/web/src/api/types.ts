import type { components } from "./schema";

/**
 * Short names for the contract's shapes, as the client returns them. openapi-fetch reads every
 * response through a `Readable` transform that turns fixed-length tuples into plain arrays; this
 * mirrors it so these types and the client's data are one and the same.
 */
type Readable<T> = T extends (infer E)[]
  ? Readable<E>[]
  : T extends object
    ? { [K in keyof T]: Readable<T[K]> }
    : T;

type Schema<K extends keyof components["schemas"]> = Readable<components["schemas"][K]>;

export type Experiment = Schema<"Experiment">;
export type ExperimentStatus = Schema<"ExperimentStatus">;
export type BuildStage = Schema<"BuildStage">;
export type Candidate = Schema<"Candidate">;
export type CandidateNetwork = Schema<"CandidateNetwork">;
export type DiseaseRef = Schema<"DiseaseRef">;
export type DiseaseSearchResult = Schema<"DiseaseSearchResult">;
export type DiseaseTarget = Schema<"DiseaseTarget">;
export type TargetExcludedReason = Schema<"TargetExcludedReason">;
export type NetworkGraph = Schema<"NetworkGraph">;
export type NetworkNode = Schema<"NetworkNode">;
export type NetworkRole = Schema<"NetworkRole">;
export type EvidenceItem = Schema<"EvidenceItem">;
export type EvidenceSource = Schema<"EvidenceSource">;
export type Warning = Schema<"Warning">;
export type Conformer = Schema<"Conformer">;
export type JuryRun = Schema<"JuryRun">;
export type JuryModel = Schema<"JuryModel">;
export type Juror = Schema<"Juror">;
export type JurorStatus = Schema<"JurorStatus">;
export type JuryVote = Schema<"JuryVote">;
export type Decision = Schema<"Decision">;
export type ExperimentSummary = Schema<"ExperimentSummary">;
export type Structure = Schema<"Structure">;
export type DockJob = Schema<"DockJob">;
export type DockFile = Schema<"DockFile">;
export type DockFiles = Schema<"DockFiles">;
export type ControlStatus = Schema<"ControlStatus">;
export type Evaluation = Schema<"Evaluation">;
export type EvaluationResult = Schema<"EvaluationResult">;
export type ConfidenceInterval = Schema<"ConfidenceInterval">;
export type EvaluationDisease = Schema<"EvaluationDisease">;
export type EvaluationScope = Schema<"EvaluationScope">;
export type EvaluationCaseStatus = Schema<"EvaluationCaseStatus">;
