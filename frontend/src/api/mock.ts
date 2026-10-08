import type { AnalysisResult, PickedVideo } from './types';

const NOTES = [
  'Timing is solid. Keep your chest lifted through the transition.',
  'You are about half a beat late on the arm extension.',
  'Left knee should bend deeper to match the reference.',
  'Good positioning. Sharpen the stop at the end of the move.',
  'Shoulders drift forward here. Stack them over your hips.',
];
const SCORES = [91, 68, 74, 88, 59];

/** Fake analysis so the UI can be built before the backend exists. */
export async function mockAnalyze(practice: PickedVideo): Promise<AnalysisResult> {
  await new Promise((resolve) => setTimeout(resolve, 1200));

  const total = practice.durationMs ? practice.durationMs / 1000 : 20;
  const length = total / NOTES.length;
  const steps = NOTES.map((feedback, i) => ({
    id: String(i + 1),
    label: `Step ${i + 1}`,
    start: Number((i * length).toFixed(2)),
    end: Number(((i + 1) * length).toFixed(2)),
    score: SCORES[i],
    feedback,
  }));
  const overallScore = Math.round(SCORES.reduce((a, b) => a + b, 0) / SCORES.length);

  return { overallScore, steps };
}
