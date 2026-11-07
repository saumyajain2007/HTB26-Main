import type { components } from "../api/schema";
import type { FailedCheck } from "../lib/jury";
import { listOf } from "../lib/format";

type BuildStage = components["schemas"]["BuildStage"];
type Decision = components["schemas"]["Decision"];
type JurorStatus = components["schemas"]["JurorStatus"];
type EvidenceSource = components["schemas"]["EvidenceSource"];
type TargetExcludedReason = components["schemas"]["TargetExcludedReason"];
type ControlStatus = components["schemas"]["ControlStatus"];
type EvaluationScope = components["schemas"]["EvaluationScope"];
type EvaluationCaseStatus = components["schemas"]["EvaluationCaseStatus"];

/** A length in ångströms, e.g. 1.74 Å or 2 Å: at most two decimals, no trailing zeros. */
function angstrom(value: number): string {
  return `${String(Number(value.toFixed(2)))} Å`;
}

/** What a model suggests doing with a drug. */
const decisions = {
  investigate: "Investigate",
  watch: "Watch",
  deprioritise: "Set aside",
} satisfies Record<Decision, string>;

/**
 * The copy deck: every sentence the interface says, in one place (docs/engineering/design.md, "Plain words").
 *
 * Only wording that holds for any Disease lives here. Text that depends on the Disease or the
 * Experiment (evidence statements, juror objections, model names, warnings, data versions) comes
 * from the API. Wording that needs a value from the API is a small function, so the sentence
 * stays here and only the value is passed in.
 *
 * Rules: sentence case, no all-caps, no arrows on buttons, no step counters, and each fact said
 * once per screen. Apostrophes are typographic (’).
 */

export const copy = {
  product: "Half Life",
  back: "Back",
  next: "Next",
  stepsLabel: "Steps",
  retry: "Try again",

  /**
   * The eight steps of plan.md §2, in order, except that Evidence sits just before History, so
   * the main path runs from the candidates straight to the jury. `slug` is the URL
   * segment in `/e/:experimentId/:step`.
   * Intros never name the Disease: the header already shows it once.
   */
  steps: [
    {
      slug: "disease",
      title: "Choose a disease",
      intro: "Start with the illness you want treatment ideas for.",
    },
    {
      slug: "biology",
      title: "Disease proteins",
      intro: "Proteins linked to the disease, and how they connect inside the cell.",
    },
    {
      slug: "candidates",
      title: "Candidate drugs",
      intro: "Approved drugs whose targets are closely tied to the disease’s proteins.",
    },
    {
      slug: "jury",
      title: "Model jury",
      intro: "AI models judged the same evidence without seeing our ranking.",
    },
    {
      slug: "compare",
      title: "Compare",
      intro: "Put candidates side by side.",
    },
    {
      slug: "pose",
      title: "Binding pose",
      intro: "How a drug might fit into its target protein, from a real crystal structure.",
    },
    {
      slug: "evidence",
      title: "Evidence",
      intro: "What we know about each drug, and where each claim comes from.",
    },
    {
      slug: "history",
      title: "History",
      intro: "Each search is saved with the data it used, so you can come back to it.",
    },
  ],

  /** The introduction at `/`: the approach, its four steps, and the way into the app. */
  intro: {
    title: "Repurposing existing drugs for diseases",
    tagline: "A second life for existing medicines",
    solution:
      "Half Life integrates biological network analysis and AI evidence review to prioritise existing drugs for further research.",
    start: "Start exploring",
    limit: "Research hypotheses, not proven treatments.",
    method: [
      {
        title: "Disease proteins",
        text: "Proteins linked to the disease, from published genetic and clinical evidence.",
      },
      {
        title: "Network ranking",
        text: "Approved drugs ranked by how closely their targets connect to those proteins.",
      },
      {
        title: "Evidence review",
        text: "Three AI models weigh the evidence for each candidate, independently.",
      },
      {
        title: "Shortlist",
        text: "Drugs worth further research, each with the reasons behind it.",
      },
    ],
    workflow: {
      title: "Workflow",
      lede: "Find existing medicines worth investigating.",
    },
  },

  search: {
    placeholder: "Search diseases",
    common: "Common diseases",
    noMatch: (query: string) => `No diseases match “${query}”. Try another name.`,
    unavailable: "Disease search isn’t answering right now.",
    createFailed: "The experiment couldn’t be started. The server isn’t answering.",
  },

  /** An Experiment while it loads, builds or fails. */
  experiment: {
    loading: "Loading the experiment",
    buildLabel: "Building the experiment",
    queued: "Waiting to start",
    stages: {
      targets: "Finding the proteins linked to the disease",
      ranking: "Ranking approved drugs",
      evidence: "Collecting the evidence for each drug",
      saving: "Saving the results",
    } satisfies Record<BuildStage, string>,
    failed: "This experiment couldn’t be built.",
    chooseAnother: "Choose another disease",
    unavailable: "The experiment couldn’t be loaded. The server isn’t answering.",
    notFound: {
      title: "Experiment not found",
      body: "There’s no saved experiment at this address.",
      home: "Choose a disease",
    },
  },

  network: {
    title: "Protein network",
    label: "Protein network in 3D. Drag to rotate.",
    unavailable: "The 3D view needs WebGL, which this browser doesn’t offer.",
    empty: "None of the disease’s proteins are in the protein network, so there’s nothing to draw.",
  },

  legend: {
    disease: "Disease protein",
    drug: "Drug target",
    both: "Both",
    link: "Connecting protein",
    path: "Shortest route",
  },

  biology: {
    rule: (linked: number, inNetwork: number) =>
      `We use the ${String(linked)} proteins most strongly linked to the disease. ${String(inNetwork)} of them appear in the protein network.`,
    /** When no network ranking ran, every linked protein is used. */
    ruleNoNetwork: (linked: number) =>
      `We use the ${String(linked)} proteins most strongly linked to the disease.`,
    noNetwork: "The protein network isn’t available for this experiment.",
    strength: "Link strength",
    targetsLabel: "Disease proteins by link strength",
    /** The proteins left out for one reason, named together in one sentence. */
    excluded: {
      not_in_graph: (symbols: readonly string[]) =>
        symbols.length === 1
          ? `${listOf(symbols)} isn’t in the protein network, so it can’t be used.`
          : `${listOf(symbols)} aren’t in the protein network, so they can’t be used.`,
      outside_largest_component: (symbols: readonly string[]) =>
        symbols.length === 1
          ? `${listOf(symbols)} sits apart from the main protein network, so it can’t be used.`
          : `${listOf(symbols)} sit apart from the main protein network, so they can’t be used.`,
    } satisfies Record<TargetExcludedReason, (symbols: readonly string[]) => string>,
  },

  candidates: {
    ranking: "Ranking",
    chartLabel: "Candidate drugs: closeness, network rank and evidence rank",
    networkRank: "Network rank",
    evidenceRank: "Evidence rank",
    evidenceRankHelp: "Ranked only by direct links between the drug’s targets and the disease.",
    randomWalkHelp:
      "Ranked by a random walk across the protein network that keeps restarting at the disease proteins: drugs whose targets it visits most rank first.",
    closeness: "Closeness",
    closenessHelp:
      "How near a drug’s targets sit to the disease proteins, compared with random proteins. Lower is closer.",
    showAll: (count: number) => `Show all ${String(count)}`,
    notMeasured: "Not measured",
    notRanked: "Not ranked",
    knownAnswer: (drug: string, disease: string) =>
      `${drug} is already used for ${disease}. Finding it shows the method works; it isn’t a new discovery.`,
    selectedBy: { network: "Network", evidence: "Evidence" },
    /** The shortlist when no network ranking ran (ranking_method evidence_only). */
    evidenceOnly: {
      title: "Ranked by evidence (protein network unavailable)",
      help: "No protein network ranking ran for this experiment, so drugs are ranked only by direct links between their targets and the disease.",
      listLabel: "Candidate drugs by evidence rank",
      rank: (rank: number) => `Evidence rank ${String(rank)}`,
    },
  },

  evidence: {
    listLabel: "Sourced facts",
    sources: {
      open_targets: "Open Targets",
      chembl: "ChEMBL",
      string: "STRING",
      reactome: "Reactome",
    } satisfies Record<EvidenceSource, string>,
    warningTitle: "Label warning",
    missingTitle: "Not yet known",
    pathTitle: "Why it ranks high",
    /** For a drug that has a route but wasn't shortlisted for its closeness. */
    routeTitle: "Its route to the disease",
    noRouteTitle: "Not on the network",
    route: {
      self: (drug: string, target: string) =>
        `${drug} acts on ${target}, which is itself a disease protein.`,
      direct: (drug: string, target: string, disease: string) =>
        `${drug} acts on ${target}, which connects directly to ${disease}, a disease protein.`,
      via: (drug: string, target: string, disease: string, through: string) =>
        `${drug} acts on ${target}, which reaches ${disease}, a disease protein, through ${through}.`,
    },
    moleculeLabel: (drug: string) => `${drug} in 3D. Drag to rotate.`,
    noModel: "Antibody: no small-molecule 3D model",
    /** No PubChem compound, and nothing says the drug is an antibody. */
    noModelNeutral: "No 3D model is available for this drug",
    modelUnavailable: "The 3D model couldn’t be loaded.",
  },

  jury: {
    ask: "Ask the Model jury",
    /** Before the jury is asked: who will review. */
    panel: (models: string) => `${models} will each review the evidence for every drug.`,
    askFailed: "The jury couldn’t be asked. The server isn’t answering.",
    archived: "This experiment is archived. Restore it in History to ask the jury.",
    progressLabel: "Model jury progress",
    queued: "Waiting to start",
    jurorStatus: {
      pending: "Waiting",
      running: "Reviewing the evidence",
      valid: "Done",
      invalid: "Its answers didn’t pass our checks",
      failed: "Didn’t answer",
    } satisfies Record<JurorStatus, string>,
    unavailable: "Review unavailable",
    /** After a failed review: why a model's answers didn't pass, completing `jurorStatus.invalid`. */
    failedCheck: {
      refused: "it declined to review the evidence",
      ranking: "it didn’t rank every drug exactly once",
      unknownEvidence: "it cited evidence that doesn’t exist",
      otherDrug: "it cited another drug’s evidence",
      uncited: "it mentioned evidence it didn’t cite",
      safety: "it misreported the recorded warnings",
      numbers: "it used numbers that aren’t in the evidence",
    } satisfies Record<FailedCheck, string>,
    invalidBecause: (reason: string) => `Its answers didn’t pass our checks: ${reason}.`,
    tableLabel: "Each model’s rank and decision for every drug",
    /** The board's first column: the drug's place in the consensus. "#" on screen. */
    consensusHead: "#",
    consensusHeadLabel: "Consensus rank",
    drug: "Drug",
    knownTreatment: "Known treatment",
    spread: "Rank spread",
    rankHelp: "The number is each model’s rank.",
    /** Read by screen readers only, in a model's cell when it didn't rank the drug. */
    noRank: "Not ranked",
    decisions,
    agreement: "Agreement",
    agreementHelp:
      "0 means no agreement between the models, 1 means full agreement. It isn’t a chance of success.",
    agreementMissing: "Fewer than two models answered, so agreement can’t be measured.",
    contestedTitle: "Split decision",
    /** The reading pane: one drug, and what each model said about it. */
    readingLabel: (drug: string) => `What the models said about ${drug}`,
    consensusRank: (rank: number) => `Consensus #${String(rank)}`,
    notInConsensus: "Not in the consensus ranking",
    /**
     * One drug's verdict in plain words: "All 3 say Investigate", "Both say Watch", or each
     * decision with how many models made it, "2 say Investigate, 1 says Watch". `everyone` is
     * true when every counted model ranked the drug.
     */
    verdict: (counts: readonly { decision: Decision; count: number }[], everyone: boolean) => {
      const [only] = counts;
      if (everyone && counts.length === 1 && only !== undefined && only.count > 1) {
        const who = only.count === 2 ? "Both" : `All ${String(only.count)}`;
        return `${who} say ${decisions[only.decision]}`;
      }
      return counts
        .map(
          ({ decision, count }) =>
            `${String(count)} ${count === 1 ? "says" : "say"} ${decisions[decision]}`,
        )
        .join(", ");
    },
    call: (decision: Decision, rank: number) => `${decisions[decision]} · rank ${String(rank)}`,
    noVote: "Didn’t rank this drug",
    objection: "Objection.",
    retried: (count: number) =>
      count === 1
        ? "One model’s first answer didn’t pass our checks, so it was asked again."
        : `${String(count)} models’ first answers didn’t pass our checks, so they were asked again.`,
    excluded: {
      invalid: (model: string) =>
        `${model}’s answers didn’t pass our checks, so it has no votes here.`,
      failed: (model: string) => `${model} didn’t answer, so it has no votes here.`,
    },
  },

  compare: {
    pick: "Change drug",
    tableLabel: "Candidate drugs side by side",
    /** Read by screen readers only: the header of the row-label column. */
    rowsHeader: "Compared on",
    decision: "Jury decision",
    targets: "Targets",
    moreTargets: (shown: string, more: number) => `${shown} and ${String(more)} more`,
    approval: "Approval",
    notRecorded: "Not recorded",
    noWarnings: "None recorded",
    /** Not "Binding pose": that is the next step's name, already in the navigation. */
    dockable: "Docking",
    pose: {
      done: (target: string) => `Computed in ${target}`,
      running: (target: string) => `Being computed in ${target}`,
      possible: (target: string) => `Possible in ${target}`,
      unavailable: "Not available",
    },
    none: "None",
    /** Only drugs with a 3D model are compared. */
    noModels: "None of these drugs has a 3D model, so there are none to compare.",
  },

  pose: {
    pick: "Change drug",
    /** The structure line: which crystal structure of which protein, and how sharp it is. */
    structure: (pdbId: string, symbol: string, resolutionAngstrom: number) =>
      `Crystal structure ${pdbId} of ${symbol}, ${angstrom(resolutionAngstrom)} resolution`,
    viewerLabel: (drug: string, protein: string) =>
      `${drug} in ${protein}, in 3D. Drag to rotate, scroll to zoom.`,
    show: "Show binding pose",
    archived: "This experiment is archived. Restore it in History to compute a pose.",
    queued: "Waiting to start",
    running: "Computing the binding pose. This can take up to three minutes.",
    failed: "The binding pose couldn’t be computed.",
    requestFailed: "The binding pose couldn’t be requested. The server isn’t answering.",
    unavailable: "Docking isn’t available right now.",
    /** Docking is down, but this pair was computed before. Replaces `unavailable`. */
    saved: "Docking isn’t available right now, so this is a saved result.",
    noFiles: "This result has a score but no 3D model to show.",
    loading: "Loading the 3D model",
    filesFailed: "The 3D model couldn’t be loaded.",
    /** On its own when no candidate drug can be docked: the drugs aren't listed. */
    noneDockable: "None of the candidate drugs can be docked yet.",
    scoresLabel: "How far to trust this pose",
    score: "Docking score",
    scoreHelp:
      "A rough fit estimate from the docking program, without units. More negative is a better fit. It isn’t a measured binding strength.",
    redock: "Redock check",
    redockHelp: (threshold: number) =>
      `We dock the crystal’s own drug back into this structure and measure how far it lands from its real position. Under ${angstrom(threshold)} means the setup finds a known answer; it says nothing about other drugs.`,
    redockStatus: {
      passed: "Good match",
      failed: "Poor match",
      not_measured: "Not measured yet",
    } satisfies Record<ControlStatus, string>,
    /** Fixture data, said once for every made-up value on the screen. */
    fixture: (result: "pose" | "score" | null, control: boolean): string | null => {
      const subject =
        result === "pose"
          ? "this pose, its docking score"
          : result === "score"
            ? "this docking score"
            : null;
      if (subject === null) return control ? "Demo data: the redock check is made up." : null;
      if (control) return `Demo data: ${subject} and the redock check are made up.`;
      return result === "pose"
        ? "Demo data: this pose and its docking score are made up."
        : "Demo data: this docking score is made up.";
    },
    caveat:
      "A pose is a guess at how a drug could sit in this pocket. It isn’t evidence that the drug binds here, or that it works.",
    controls: {
      surface: "Pocket surface",
      overlay: "Crystal position",
      spin: "Spin",
      reset: "Reset view",
    },
    legend: { protein: "Protein", drug: "Drug" },
  },

  history: {
    viewLabel: "Which experiments to list",
    listLabel: "Experiments",
    active: "Saved",
    archived: "Archived",
    archive: "Archive",
    restore: "Restore",
    current: "Open",
    loading: "Loading saved experiments",
    unavailable: "Saved experiments couldn’t be loaded. The server isn’t answering.",
    emptyActive: "No saved experiments yet.",
    emptyArchived: "No archived experiments.",
    counts: (candidates: number, docked: number) =>
      `${String(candidates)} candidate ${candidates === 1 ? "drug" : "drugs"}, ${String(docked)} binding ${docked === 1 ? "pose" : "poses"}`,
    actionFailed: "That didn’t work. The server isn’t answering.",
    data: (versions: readonly string[]) => `Data: ${versions.join(", ")}`,
  },

  /** `/evaluation`: how well each ranking finds drugs already approved for a disease. */
  evaluation: {
    title: "How well the ranking works",
    /** The way into the steps, in the header. */
    start: "Choose a disease",
    intro:
      "A test on past data: for diseases that already have approved treatments, how high does each ranking put them?",
    loading: "Loading the test results",
    unavailable: "The test results couldn’t be loaded. The server isn’t answering.",
    empty: "No test results yet.",
    example: "Example numbers: the real test hasn’t run yet.",
    resultsTitle: "Known treatments found",
    scopeLabel: "Which drugs to rank",
    scopes: {
      full_eligible: "All approved drugs",
      common_scorable: "Drugs every ranking can place",
    } satisfies Record<EvaluationScope, string>,
    method: "Ranking",
    ours: "The app’s main ranking",
    /** Names for stream B's methods; an unknown one shows its code. */
    methods: {
      degree_matched_z: "Network closeness",
      direct_evidence: "Disease link strength",
      shared_targets: "Shared proteins",
      raw_proximity: "Network distance alone",
      random: "Random order",
    } as Record<string, string | undefined>,
    metrics: {
      recall_at_5: "In top 5",
      recall_at_10: "In top 10",
      recall_at_20: "In top 20",
      mrr: "First hit score",
    },
    missing: "No value",
    range: (low: string, high: string) => `likely between ${low} and ${high}`,
    howToRead: [
      "In top 5, 10 and 20: the share of each disease’s known treatments that the ranking puts that high.",
      "First hit score: 1 when a known treatment comes first, 0.5 when second, near 0 when the first is far down.",
    ],
    rangeNote: "Lines show where each score likely lies (95% range).",
    testedTitle: "Diseases tested",
    found: (known: number, candidates: number) =>
      `${String(known)} known ${known === 1 ? "treatment" : "treatments"} among ${candidates.toLocaleString("en-GB")} drugs`,
    leftOut: {
      missing_labels: "Left out: no known treatments are recorded.",
      no_positive_references: "Left out: its record lists no known treatments.",
      no_positive_in_scope: "Left out: none of its known treatments are among these drugs.",
      empty_universe: "Left out: there are no drugs to rank.",
    } satisfies Record<Exclude<EvaluationCaseStatus, "evaluated">, string>,
    limitsTitle: "Keep in mind",
    tooFew: (count: number) =>
      `Only ${String(count)} ${count === 1 ? "disease" : "diseases"} counted: too few to draw a conclusion.`,
    limits: [
      "The known treatments come from the same public data the rankings read, so this isn’t an independent test.",
      "A drug not yet approved for a disease isn’t proof it doesn’t work.",
    ],
    record: (hash: string, versions: readonly string[], date: string) =>
      `Frozen record ${hash.slice(0, 12)}, ${date}. Data: ${versions.join(", ")}`,
  },

  notFound: {
    title: "Page not found",
    body: "There’s nothing at this address.",
    home: "Choose a disease",
  },

  routeError: {
    title: "Something went wrong",
    body: "This page couldn’t be shown. Reload to try again.",
    home: "Choose a disease",
  },
} as const;

export type StepCopy = (typeof copy.steps)[number];
export type StepSlug = StepCopy["slug"];

export const stepSlugs: readonly StepSlug[] = copy.steps.map((step) => step.slug);

export function isStepSlug(value: string | undefined): value is StepSlug {
  return value !== undefined && (stepSlugs as readonly string[]).includes(value);
}

export function stepIndex(slug: StepSlug): number {
  return stepSlugs.indexOf(slug);
}

export function stepCopy(slug: StepSlug): StepCopy {
  const step = copy.steps.find((candidate) => candidate.slug === slug);
  if (step === undefined) throw new Error(`No copy for step "${slug}"`);
  return step;
}

/**
 * Why a Candidate can't be scored on the protein network. The codes come from the API
 * contract, so a new code fails to compile until it has wording here.
 */
export type UnscorableReason = components["schemas"]["UnscorableReason"];

export const unscorableReasons: Record<UnscorableReason, string> = {
  no_retained_disease_targets:
    "None of the disease’s proteins are in the protein network, so no drug can be placed near them.",
  no_retained_drug_targets:
    "None of this drug’s targets are human proteins in the network, so it has no place in it.",
  network_unavailable:
    "No protein network ranking ran for this experiment, so this drug has no route to the disease to show.",
};

/** Why a network score is incomplete or less reliable. Same compile-time guarantee. */
export type NetworkWarning = components["schemas"]["NetworkWarning"];

export const networkWarnings: Record<NetworkWarning, string> = {
  zero_null_variance:
    "Random proteins all landed at the same distance, so closeness can’t be measured. Ranked by distance only.",
  insufficient_degree_matched_pool:
    "Too few comparable proteins to compare against, so closeness is less reliable.",
};

export function networkWarningText(warning: NetworkWarning): string {
  return networkWarnings[warning];
}

export function unscorableReasonText(reason: UnscorableReason): string {
  return unscorableReasons[reason];
}
