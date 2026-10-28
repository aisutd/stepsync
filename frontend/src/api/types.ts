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
};

export type AnalysisResult = {
  /** Set by the backend so a result can be looked up later. */
  sessionId?: string;
  overallScore: number;
  steps: StepFeedback[];
};
