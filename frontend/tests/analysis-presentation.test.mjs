import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisPresentation } from '../src/api/analysis-presentation.ts';

const step = { id: '1', label: 'Knee', start: 3.2, end: 4, score: 70, feedback: 'Measured knee difference.' };
const completed = {
  overallScore: 83.94, movementScore: 83.94, status: 'completed', scoreAvailable: true,
  globalScoreAvailable: true, scoreScope: 'aligned_observations', coverage: { assessed: 0.6154 },
  assessment: { totalFrames: 780, assessedFrames: 480, unassessedFrames: 300 },
  comparisonSegments: [{ start: 3.1, end: 6.167, status: 'supported' }], steps: [step],
};

test('completed with global eligibility still shows 61.54% coverage and 300 unassessed frames', () => {
  const view = analysisPresentation(completed);
  assert.equal(view.globalScore, 83.94);
  assert.equal(view.partialScore, null);
  assert.equal(view.coverageText, '480 / 780 frames assessed (61.54%)');
  assert.equal(view.unassessedText, '300 frames unassessed. Unassessed movements are not judged.');
});

test('partial score never becomes the analysis-wide score', () => {
  const view = analysisPresentation({ ...completed, status: 'partial', globalScoreAvailable: false,
    scoreScope: 'supported_segments', overallScore: 82.76, movementScore: 82.76,
    assessment: { totalFrames: 780, assessedFrames: 36, unassessedFrames: 744 } });
  assert.equal(view.globalScore, null);
  assert.equal(view.partialScore, 82.76);
  assert.equal(view.coverageText, '36 / 780 frames assessed (4.62%)');
});

test('no score does not display the legacy zero as a grade', () => {
  const view = analysisPresentation({ ...completed, status: 'uncertain_alignment', globalScoreAvailable: false,
    scoreScope: 'none', scoreAvailable: false, overallScore: 0, movementScore: null,
    assessment: { totalFrames: 780, assessedFrames: 0, unassessedFrames: 780 } });
  assert.equal(view.globalScore, null);
  assert.equal(view.partialScore, null);
  assert.equal(view.coverageText, '0 / 780 frames assessed (0.00%)');
  assert.deepEqual(view.steps, []);
});

test('feedback cannot cross unassessed sections or claim an unassessed movement', () => {
  const view = analysisPresentation({ ...completed, steps: [step,
    { ...step, id: '2', start: 6, end: 9 },
    { ...step, id: '3', start: 9, end: 10 },
    { ...step, id: '4', evidence: { status: 'unassessed' } },
  ] });
  assert.deepEqual(view.steps.map((s) => s.id), ['1']);
});

test('older full responses derive exact counts from frame records', () => {
  const view = analysisPresentation({ ...completed, assessment: undefined,
    frameComparisons: [{ status: 'compared' }, { status: 'unassessed' }, { status: 'compared' }] });
  assert.equal(view.coverageText, '2 / 3 frames assessed (66.67%)');
});

test('coverage is reported even without frame records', () => {
  const view = analysisPresentation({ ...completed, assessment: undefined, frameComparisons: undefined });
  assert.equal(view.coverageText, '61.54% of practice frames assessed');
});

test('legacy payloads without scope cannot invent full coverage or a global score', () => {
  const view = analysisPresentation({ overallScore: 99, steps: [step] });
  assert.equal(view.coverageText, 'Assessment coverage unavailable');
  assert.equal(view.globalScore, null);
  assert.equal(view.partialScore, null);
  assert.deepEqual(view.steps, []);
});

test('contradictory scope or zero evidence suppresses numbers and feedback', () => {
  for (const result of [
    { ...completed, status: 'partial' },
    { ...completed, assessment: { totalFrames: 780, assessedFrames: 0, unassessedFrames: 780 } },
    { ...completed, movementScore: Number.NaN },
    { ...completed, assessment: undefined, coverage: { assessed: 3 } },
  ]) {
    const view = analysisPresentation(result);
    assert.equal(view.globalScore, null);
    assert.equal(view.partialScore, null);
    assert.deepEqual(view.steps, []);
  }
});

test('fully assessed frames do not turn scope flags into a correctness claim', () => {
  const view = analysisPresentation({ ...completed,
    assessment: { totalFrames: 12, assessedFrames: 12, unassessedFrames: 0 } });
  assert.equal(view.coverageText, '12 / 12 frames assessed (100.00%)');
  assert.match(view.unassessedText, /Unassessed movements are not judged/);
});

test('compact API summary needs no frame or diagnostic download to render results', () => {
  const summary = { ...completed, createdAt: '2026-10-29T00:00:00Z', expiresAt: '2026-11-05T00:00:00Z',
    links: { summary: '/analyses/example', frames: '/analyses/example/frames',
      diagnostics: '/analyses/example/diagnostics', download: '/analyses/example/diagnostics?download=true' } };
  assert.equal('frameComparisons' in summary, false);
  assert.equal('diagnostics' in summary, false);
  const view = analysisPresentation(summary);
  assert.equal(view.globalScore, 83.94);
  assert.equal(view.coverageText, '480 / 780 frames assessed (61.54%)');
  assert.deepEqual(view.steps, [step]);
});


test('ambiguous mapping withholds candidate scores and feedback but permits automatic conservative coaching', () => {
  for (const requestedMode of ['auto', 'same', 'mirrored']) {
    const view = analysisPresentation({ ...completed, alignment: { mirrorSelection: { ambiguous: true, requestedMode } } });
    assert.equal(view.mappingAmbiguous, true);
    assert.equal(view.coachingAllowed, true);
    assert.equal(view.globalScore, null);
    assert.equal(view.partialScore, null);
    assert.deepEqual(view.steps, []);
    assert.equal(view.coverageText, '480 / 780 frames assessed (61.54%)');
  }
});

test('manual convention does not force a score without alignment evidence', () => {
  const view = analysisPresentation({ ...completed, scoreAvailable: false, globalScoreAvailable: false,
    alignment: { mirrorSelection: { ambiguous: false, requestedMode: 'same' } } });
  assert.equal(view.mappingAmbiguous, false);
  assert.equal(view.globalScore, null);
  assert.deepEqual(view.steps, []);
});
