import type { AnalysisResult } from './types';

/** Present scope and coverage without inferring success from a legacy number. */
export function analysisPresentation(result: AnalysisResult) {
  let counts: { totalFrames: number; assessedFrames: number; unassessedFrames: number } | null = null;
  const supplied = result.assessment;
  if (supplied && [supplied.totalFrames, supplied.assessedFrames, supplied.unassessedFrames]
    .every((n) => Number.isInteger(n) && n >= 0) && supplied.totalFrames > 0
    && supplied.assessedFrames + supplied.unassessedFrames === supplied.totalFrames) {
    counts = supplied;
  } else if (result.frameComparisons?.length && result.frameComparisons
    .every((frame) => frame.status === 'compared' || frame.status === 'unassessed')) {
    const totalFrames = result.frameComparisons.length;
    const assessedFrames = result.frameComparisons.filter((frame) => frame.status === 'compared').length;
    counts = { totalFrames, assessedFrames, unassessedFrames: totalFrames - assessedFrames };
  }
  const reported = result.coverage?.assessed;
  const fraction = counts ? counts.assessedFrames / counts.totalFrames
    : typeof reported === 'number' && Number.isFinite(reported) && reported >= 0 && reported <= 1 ? reported : null;
  const coverageText = fraction === null ? 'Assessment coverage unavailable'
    : counts ? `${counts.assessedFrames} / ${counts.totalFrames} frames assessed (${(fraction * 100).toFixed(2)}%)`
      : `${(fraction * 100).toFixed(2)}% of practice frames assessed`;
  const unassessedText = counts ? `${counts.unassessedFrames} frames unassessed. Unassessed movements are not judged.`
    : 'Unassessed movements are not judged.';
  const score = result.movementScore;
  const hasScore = result.scoreAvailable === true && fraction !== null && fraction > 0
    && typeof score === 'number' && Number.isFinite(score) && score >= 0 && score <= 100;
  const globalScore = hasScore && result.globalScoreAvailable === true
    && result.status === 'completed' && result.scoreScope === 'aligned_observations' ? score : null;
  const partialScore = hasScore && result.globalScoreAvailable === false
    && result.status === 'partial' && result.scoreScope === 'supported_segments' ? score : null;
  const supported = (result.comparisonSegments ?? []).filter((segment) => segment.status === 'supported'
    && Number.isFinite(segment.start) && Number.isFinite(segment.end) && segment.start <= segment.end);
  // Feedback must lie inside an explicitly supported span. Legacy/contradictory
  // payloads cannot turn a stored numeric score into a claim about unseen motion.
  const steps = globalScore !== null || partialScore !== null ? result.steps.filter((step) =>
    step.evidence?.status !== 'unassessed' && Number.isFinite(step.start) && Number.isFinite(step.end)
    && step.start <= step.end && supported.some((span) => step.start >= span.start && step.end <= span.end)) : [];
  return { globalScore, partialScore, coverageText, unassessedText, steps, supported };
}
