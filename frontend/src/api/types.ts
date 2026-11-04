// The contract between the app and the FastAPI backend.
// Change it here first, then mirror it in the backend's response model.

export type MirrorMode = 'auto' | 'same' | 'mirrored';

export type CoachingMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  source: 'user' | 'gemini' | 'evidence';
  createdAt: string;
  citations: { id: string; label: string; start: number; end: number; fact: string }[];
};

export type CoachingConversation = {
  sessionId: string;
  enabled: boolean;
  coverageStatement: string;
  scoreScope: string;
  messages: CoachingMessage[];
  remainingQuestions: number;
  notice: string;
};

export type PickedVideo = {
  uri: string;
  fileName: string;
  mimeType: string;
  durationMs: number | null;
  /** Set when the video came from a YouTube link instead of the phone. */
  youtube?: YouTubeSource;
};

export type YouTubeSource = {
  /** Saved dance ID for server-side DTW; avoids reuploading a signed URL. */
  danceId?: string;
  url: string;
  videoId: string;
  isShort: boolean;
  title: string;
  /** Name the backend saved it under; null in mock mode (nothing was downloaded). */
  serverFilename: string | null;
  playbackUrl?: string;
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
  referenceStart?: number;
  referenceEnd?: number;
  evidence?: { kind?: string; status?: string };
};

export type AnalysisResult = {
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
  timingScore?: number;
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
