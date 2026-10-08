// The contract between the app and the FastAPI backend.
// Change it here first, then mirror it in the backend's response model.

export type PickedVideo = {
  uri: string;
  fileName: string;
  mimeType: string;
  durationMs: number | null;
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
  overallScore: number;
  steps: StepFeedback[];
};
