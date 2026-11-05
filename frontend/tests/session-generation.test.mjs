import assert from 'node:assert/strict';
import test from 'node:test';
import { createSessionHarness } from './helpers/session-harness.mjs';

test('video selection and result changes synchronously invalidate outstanding result requests', async () => {
  for (const change of ['setReference', 'setPractice', 'clearResult', 'replaceResult']) {
    const harness = await createSessionHarness();
    const original = { sessionId: 'original', steps: [] };
    harness.session.setResult(original);
    const session = harness.session;
    const pending = session.beginResultRequest();
    if (change === 'clearResult') session.setResult(null);
    else if (change === 'replaceResult') session.setResult({ sessionId: 'new-analysis', steps: [] });
    else session[change]({ uri: 'new-video' });
    // No rerender needed for invalidation: the generation changes in the setter.
    assert.equal(pending.isCurrent(), false);
    assert.equal(pending.commit({ sessionId: 'stale', steps: [] }), false);
    assert.notEqual(harness.session.result?.sessionId, 'stale');
  }
});

test('a new analysis request wins even when the old retry completes first', async () => {
  const harness = await createSessionHarness();
  const retry = harness.session.beginResultRequest();
  const analysis = harness.session.beginResultRequest();
  assert.equal(retry.commit({ sessionId: 'old-retry', steps: [] }), false);
  assert.equal(analysis.commit({ sessionId: 'new-analysis', steps: [] }), true);
  assert.equal(retry.commit({ sessionId: 'old-retry', steps: [] }), false);
  assert.equal(analysis.commit({ sessionId: 'duplicate', steps: [] }), false);
  assert.equal(harness.session.result.sessionId, 'new-analysis');
});
