// The contract between the app and the FastAPI backend.
// Change it here first, then mirror it in the backend's response model.

export type PickedVideo = {
  uri: string;
  fileName: string;
  mimeType: string;
  durationMs: number | null;
  /** Set when the video came from a YouTube link instead of the phone. */
  youtube?: YouTubeSource;
};

export type YouTubeSource = {
  url: string;
  videoId: string;
  isShort: boolean;
  title: string;
  /** Name the backend saved it under; null in mock mode (nothing was downloaded). */
  serverFilename: string | null;
  /** Set when the video saved but Kaitlyn's pose extraction failed on it. */
  poseWarning?: string;
  /** Learnable steps the backend found in the dance. */
  steps?: DanceStep[];
};

/** One learnable step found by backend/app/segmentation.py. */
export type DanceStep = {
  step_index: number;
  label: string;
  start_ms: number;
  end_ms: number;
  intensity: 'slow' | 'medium' | 'fast';
  /** Body parts moving more than usual in this step. */
  focus: ('arms' | 'legs' | 'head' | 'torso')[];
};

/** A dance saved in Supabase, as GET /dances lists it. */
export type DanceSummary = {
  id: string;
  title: string;
  source_url: string | null;
  /** Filename on the backend that saved it (GET /videos/{video_path}). */
  video_path: string | null;
  /** False when another teammate's backend saved it, so this backend can't play it. */
  video_available: boolean;
  duration_ms: number | null;
  status: 'processing' | 'ready' | 'failed';
  is_public: boolean;
  /** True for the signed-in user's own dances (only those can be edited). */
  mine: boolean;
  step_count: number;
  created_at: string | null;
};

/** GET /dances/{id}: a dance with its steps. */
export type DanceDetail = DanceSummary & { steps: DanceStep[] };

/** Response of POST /reference-videos (Rodrigo's YouTube intake). */
export type YouTubeImportResponse = {
  status: 'uploaded' | 'processing' | 'completed' | 'failed';
  source_url: string;
  filename: string;
  size_bytes: number;
  metadata: { duration_seconds: number; width: number; height: number; fps: number };
  pose_processing: string;
  persisted: boolean;
  pose_error?: string | null;
  /** Whether the keypoints and motion features reached Supabase. */
  supabase_status: 'saved' | 'not_configured' | 'skipped' | 'failed';
  supabase_dance_id?: string | null;
  supabase_error?: string | null;
  frames_saved?: number | null;
  steps?: DanceStep[];
};

export type StepFeedback = {
  id: string;
  label: string;
  /** Seconds into the practice video. */
  start: number;
  end: number;
  /** Similarity to the reference, 0 to 100. */
  score: number;
  feedback: string;
  evidence?: { kind?: string; status?: string };
};

export type AnalysisResult = {
  sideIndependentEvidence?: Record<string, unknown> | null;
  /** Set by the backend so a result can be looked up later. */
  sessionId?: string;
  overallScore: number;
  steps: StepFeedback[];
  status?: 'completed' | 'partial' | 'insufficient_data' | 'uncertain_viewpoint' | 'uncertain_alignment';
  scoreAvailable?: boolean;
  /** Analysis-wide eligibility passed; does NOT imply every frame/joint was assessed. */
  globalScoreAvailable?: boolean;
  scoreScope?: 'none' | 'aligned_observations' | 'supported_segments';
  movementScore?: number | null;
  reason?: string | null;
  warnings?: string[];
  alignment?: {
    mirrored?: boolean | null;
    mirrorSelection?: { requestedMode?: MirrorMode; decision?: string; ambiguous?: boolean; selectedMapping?: 'same' | 'mirrored' | null; reason?: string };
  };
  coverage?: { assessed?: number; compared?: number; reference?: number; practice?: number };
  assessment?: { totalFrames: number; assessedFrames: number; unassessedFrames: number } | null;
  frameComparisons?: { status: 'compared' | 'unassessed' }[];
  comparisonSegments?: { start: number; end: number; status: 'supported' | 'unassessed' }[];
  createdAt?: string;
  expiresAt?: string;
  links?: { summary: string; frames: string; diagnostics: string; download: string };
};

export type FrameComparison = {
  practiceFrameIndex: number | null;
  practiceTime: number;
  referenceFrameIndex: number | null;
  referenceTime: number | null;
  candidateReferenceFrameIndex?: number | null;
  candidateReferenceTime?: number | null;
  status: 'compared' | 'unassessed';
  reason?: string | null;
  reasons?: string[];
  joints: {
    bodyPart: string;
    referenceBodyPart: string;
    expected: number | null;
    observed: number | null;
    difference: number | null;
    signedDifference: number | null;
    units: string;
    status: 'matched' | 'different' | 'unassessed';
    confidence: number;
    reason?: string | null;
    reasons?: string[];
  }[];
  alignmentEvidence?: Record<string, unknown> | null;
};

export type FrameComparisonPage = {
  sessionId: string;
  total: number;
  offset: number;
  limit: number;
  returned: number;
  hasMore: boolean;
  nextOffset: number | null;
  items: FrameComparison[];
};

export type MirrorMode = 'auto' | 'same' | 'mirrored';

export type CoachingSummary = {
  impression: string;
  strengths: string[];
  improvements: string[];
  practiceTip: string | null;
  note: string | null;
};

export type CoachingMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  source: 'user' | 'gemini' | 'evidence';
  createdAt: string;
  citations: { id: string; label: string; start: number; end: number; fact: string }[];
};

export type CoachingConversation = {
  initialReady?: boolean;
  initialMessageId?: string | null;
  summary?: CoachingSummary | null;
  sessionId: string;
  enabled: boolean;
  coverageStatement: string;
  scoreScope: string;
  messages: CoachingMessage[];
  remainingQuestions: number;
  notice: string;
};
