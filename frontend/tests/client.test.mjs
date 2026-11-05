import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';

// Execute the real client with only its platform boundary replaced. No RN renderer needed.
let source = stripTypeScriptTypes(readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8'));
source = source.replace("import { Platform } from 'react-native';", "const Platform = { OS: 'web' };")
  .replace("import { mockAnalyze } from './mock';", "const mockAnalyze = () => { throw new Error('Unexpected mock analysis'); };");
delete process.env.EXPO_PUBLIC_API_URL;
const client = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const video = { uri: URL.createObjectURL(new Blob(['video'], { type: 'video/mp4' })), fileName: 'dance.mp4', mimeType: 'video/mp4', durationMs: 4000 };
let sent;
let response = { status: 200, body: { sessionId: 'a'.repeat(32), overallScore: 82, steps: [], status: 'partial', scoreAvailable: true, globalScoreAvailable: false, scoreScope: 'supported_segments', movementScore: 82, assessment: { totalFrames: 100, assessedFrames: 30, unassessedFrames: 70 } } };
class Request {
  upload = {};
  open(method, url) { this.method = method; this.url = url; }
  send(body) {
    sent = { body, url: this.url, method: this.method, timeout: this.timeout };
    queueMicrotask(() => {
      if (response.network) return this.onerror();
      if (response.timeout) return this.ontimeout();
      this.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
      this.upload.onload();
      this.status = response.status;
      this.responseText = JSON.stringify(response.body);
      this.onload();
    });
  }
}
globalThis.XMLHttpRequest = Request;

test('browser uploads two actual files to local /analyze and consumes compact summary', async () => {
  const progress = [];
  const result = await client.analyze(video, video, (value) => progress.push(value));
  assert.equal(client.usingMockApi, false);
  assert.equal(sent.url, 'http://127.0.0.1:8000/analyze');
  assert.equal(sent.method, 'POST');
  assert.equal(sent.body.get('reference').name, 'dance.mp4');
  assert.equal(await sent.body.get('practice').text(), 'video');
  assert.equal(sent.body.get('mirror_mode'), 'auto');
  assert.deepEqual(progress, [0.5, 1]);
  assert.equal(result.globalScoreAvailable, false);
  assert.equal(result.assessment.assessedFrames, 30);
  assert.equal('frameComparisons' in result, false);
  assert.ok(sent.timeout >= 20 * 60 * 1000);
});

test('explicit retry sends selected mirror convention without fetching diagnostics', async () => {
  for (const mode of ['same', 'mirrored']) {
    await client.analyze(video, video, undefined, mode);
    assert.equal(sent.body.get('mirror_mode'), mode);
  }
});

test('backend error explanations survive transport', async () => {
  for (const body of [{ error: { code: 'POSE_FAILED', message: 'No usable pose data.' } }, { detail: 'No usable pose data.' }, { detail: [{ msg: 'No usable pose data.' }] }]) {
    response = { status: 422, body };
    await assert.rejects(client.analyze(video, video), /No usable pose data/);
  }
});

test('network failures and processing timeouts have actionable messages', async () => {
  response = { network: true };
  await assert.rejects(client.analyze(video, video), /Start the backend/);
  response = { timeout: true };
  await assert.rejects(client.analyze(video, video), /Analysis timed out.*shorter videos/);
});

test('coaching requests use only a session ID and question, and keep provider failures separate', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  let fail = false;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify(fail ? { detail: 'Gemini is temporarily unavailable.' } : {
      sessionId: 'a'.repeat(32), enabled: true, messages: [], remainingQuestions: 20,
      coverageStatement: '36 of 780 frames were assessed.', scoreScope: 'supported_segments', notice: 'Saved evidence only.',
    }), { status: fail ? 503 : 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    const saved = await client.getCoaching('a'.repeat(32));
    assert.equal(saved.scoreScope, 'supported_segments');
    await client.askCoach('a'.repeat(32));
    assert.deepEqual(JSON.parse(requests[1].options.body), { requestId: 'initial' });
    await client.askCoach('a'.repeat(32), 'My arms at 7 seconds?', 'question_1');
    assert.equal(requests[2].url, `http://127.0.0.1:8000/analyses/${'a'.repeat(32)}/coaching`);
    assert.deepEqual(JSON.parse(requests[2].options.body), { message: 'My arms at 7 seconds?', requestId: 'question_1' });
    assert.equal(requests[2].options.method, 'POST');
    assert.equal('Authorization' in requests[2].options.headers, false);
    fail = true;
    await assert.rejects(client.askCoach('a'.repeat(32)), /Gemini is temporarily unavailable/);
    await assert.rejects(client.askCoach('invalid'), /Invalid analysis session ID/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test('recompare sends JSON only, deduplicates in-flight retries, and returns a new result', async () => {
  const originalFetch = globalThis.fetch;
  let resolveResponse;
  const calls = [];
  globalThis.fetch = (url, options) => {
    calls.push({ url, options });
    return new Promise((resolve) => { resolveResponse = resolve; });
  };
  try {
    const id = 'a'.repeat(32);
    const first = client.retryAnalysis(id, 'same');
    const duplicate = client.retryAnalysis(id, 'same');
    assert.equal(first, duplicate);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, `http://127.0.0.1:8000/analyses/${id}/recompare`);
    assert.deepEqual(JSON.parse(calls[0].options.body), { mirrorMode: 'same' });
    resolveResponse(new Response(JSON.stringify({ sessionId: 'b'.repeat(32) }), { status: 200 }));
    assert.equal((await first).sessionId, 'b'.repeat(32));
  } finally { globalThis.fetch = originalFetch; }
});

test('different side overrides do not reuse a pending response for the other convention', async () => {
  const originalFetch = globalThis.fetch;
  const pending = [];
  globalThis.fetch = (_url, options) => new Promise(resolve => pending.push({ mode: JSON.parse(options.body).mirrorMode, resolve }));
  try {
    const same = client.retryAnalysis('e'.repeat(32), 'same');
    const mirrored = client.retryAnalysis('e'.repeat(32), 'mirrored');
    assert.notEqual(same, mirrored);
    assert.deepEqual(pending.map(request => request.mode), ['same', 'mirrored']);
    for (const request of pending) request.resolve(new Response(JSON.stringify({ mode: request.mode }), { status: 200 }));
    assert.equal((await same).mode, 'same');
    assert.equal((await mirrored).mode, 'mirrored');
  } finally { globalThis.fetch = originalFetch; }
});

test('retry errors preserve the caller result and do not silently upload expired sessions', async () => {
  const originalFetch = globalThis.fetch;
  const previous = Object.freeze({ sessionId: 'a'.repeat(32) });
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Analysis session has expired.' }), { status: 410 });
  try {
    await assert.rejects(client.retryAnalysis(previous.sessionId, 'same', video, video), /expired/);
    assert.equal(previous.sessionId, 'a'.repeat(32));
    // Failure clears the duplicate guard, so a subsequent attempt can succeed.
    globalThis.fetch = async () => new Response(JSON.stringify({ sessionId: 'c'.repeat(32) }), { status: 200 });
    assert.equal((await client.retryAnalysis(previous.sessionId, 'mirrored')).sessionId, 'c'.repeat(32));
  } finally { globalThis.fetch = originalFetch; }
});

test('only missing saved CSVs fall back to the existing manual video upload', async () => {
  const originalFetch = globalThis.fetch;
  response = { status: 200, body: { sessionId: 'd'.repeat(32) } };
  globalThis.fetch = async (url, options) => options?.method === 'POST'
    ? new Response(JSON.stringify({ detail: { code: 'pose_data_missing', message: 'Upload videos again.' } }), { status: 409 })
    : originalFetch(url, options);
  try {
    assert.equal((await client.retryAnalysis('a'.repeat(32), 'mirrored', video, video)).sessionId, 'd'.repeat(32));
    assert.equal(sent.body.get('mirror_mode'), 'mirrored');
    await assert.rejects(client.retryAnalysis('b'.repeat(32), 'same'), /Upload videos again/);
    await assert.rejects(client.recompareAnalysis('invalid', 'same'), /Invalid analysis session ID/);
    await assert.rejects(client.recompareAnalysis('a'.repeat(32), 'auto'), /Choose same or mirrored/);
  } finally { globalThis.fetch = originalFetch; }
});
