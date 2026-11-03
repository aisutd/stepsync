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
