import { Platform } from 'react-native';

import { supabase, supabaseConfigured } from '@/lib/supabase';

import { mockAnalyze } from './mock';
import type { AnalysisResult, CoachingConversation, FrameComparisonPage, MirrorMode, DanceDetail, DanceStep, DanceSummary, PickedVideo, YouTubeImportResponse } from './types';

const API_URL = (process.env.EXPO_PUBLIC_API_URL || (Platform.OS === 'web' ? 'http://127.0.0.1:8000' : undefined))?.replace(/\/+$/, '');

/** Browser sessions use the local backend; native sessions need EXPO_PUBLIC_API_URL. */
export const usingMockApi = !API_URL;

/**
 * Uploads the practice video and the reference to POST /analyze and returns the feedback.
 * A YouTube reference is already on the server, so only its saved filename is sent.
 * `onProgress` gets 0 to 1 as the upload goes; at 1 the server is analyzing.
 */
export async function analyze(
  reference: PickedVideo,
  practice: PickedVideo,
  onProgress?: (fraction: number) => void,
  /** Score against just this part of the reference (one tutorial step). */
  step?: { start_ms: number; end_ms: number },
  mirrorMode: MirrorMode = 'auto',
): Promise<AnalysisResult> {
  if (!API_URL) return mockAnalyze(practice);

  const body = new FormData();
  body.append('mirror_mode', mirrorMode);
  const savedYouTube = reference.youtube?.serverFilename;
  if (savedYouTube) body.append('reference_video', savedYouTube);
  else await appendVideo(body, 'reference', reference);
  await appendVideo(body, 'practice', practice);
  if (step) {
    body.append('step_start_ms', String(Math.round(step.start_ms)));
    body.append('step_end_ms', String(Math.round(step.end_ms)));
  }

  return postForm<AnalysisResult>(`${API_URL}/analyze`, body, onProgress);
}

/**
 * Asks the backend to download a YouTube video or Short (POST /reference-videos).
 * The backend also runs pose extraction before answering, so this can take minutes.
 */
export async function importYouTube(url: string): Promise<YouTubeImportResponse> {
  if (!API_URL) throw new Error('Connect the backend (EXPO_PUBLIC_API_URL) to import YouTube links.');

  const controller = new AbortController();
  // Matches the backend's 10-minute pose-processing limit, plus download time.
  const timer = setTimeout(() => controller.abort(), 12 * 60 * 1000);
  try {
    const response = await fetch(`${API_URL}/reference-videos`, {
      method: 'POST',
      // The login token lets the backend save the dance under this user in Supabase.
      headers: { 'Content-Type': 'application/json', ...(await authHeader()) },
      body: JSON.stringify({ url }),
      signal: controller.signal,
    });
    const text = await response.text();
    if (!response.ok) throw new Error(errorMessage(text, response.status));
    return JSON.parse(text) as YouTubeImportResponse;
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') throw new Error('The import timed out. Try a shorter video.');
    if (e instanceof TypeError) throw new Error(unreachable());
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** The signed-in user's dances and public ones, newest first (GET /dances). */
export async function listDances(): Promise<DanceSummary[]> {
  return (await getJson<{ dances: DanceSummary[] }>('/dances')).dances;
}

/** One saved dance with its steps (GET /dances/{id}). */
export function getDance(danceId: string): Promise<DanceDetail> {
  return getJson<DanceDetail>(`/dances/${encodeURIComponent(danceId)}`);
}

async function getJson<T>(path: string): Promise<T> {
  if (!API_URL) throw new Error('Connect the backend (EXPO_PUBLIC_API_URL) to see your dances.');
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { headers: await authHeader() });
  } catch {
    throw new Error(unreachable());
  }
  const text = await response.text();
  if (!response.ok) throw new Error(errorMessage(text, response.status));
  return JSON.parse(text) as T;
}

async function authHeader(): Promise<Record<string, string>> {
  if (!supabaseConfigured) return {};
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// fetch() can't report upload progress, so this uses XMLHttpRequest,
// which works the same in React Native and the browser.
function postForm<T>(
  url: string,
  body: FormData,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.timeout = 5 * 60 * 1000;

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(errorMessage(xhr.responseText, xhr.status)));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch {
        reject(new Error('The server sent back something that is not JSON.'));
      }
    };
    xhr.onerror = () => reject(new Error(unreachable()));
    xhr.ontimeout = () => reject(new Error('The upload timed out.'));

    xhr.send(body);
  });
}

function unreachable(): string {
  return (
    `Couldn't reach ${API_URL}. Is the backend running with --host 0.0.0.0, ` +
    'and is your phone on the same Wi-Fi?'
  );
}

// The backend uses two error shapes: FastAPI's {"detail": "..."} and
// Rodrigo's {"error": {"code": "...", "message": "..."}}.
function errorMessage(responseText: string, status: number): string {
  try {
    const body = JSON.parse(responseText);
    if (typeof body?.error?.message === 'string') return body.error.message;
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    // fall through to the generic message
  }
  return `Request failed (${status}).`;
}

async function appendVideo(body: FormData, field: string, video: PickedVideo) {
  if (Platform.OS === 'web') {
    // In the browser the picked uri is a blob: URL, so read it into a real Blob.
    const blob = await (await fetch(video.uri)).blob();
    body.append(field, blob, video.fileName);
    return;
  }
  // React Native's FormData takes a { uri, name, type } object for file uploads.
  body.append(field, {
    uri: video.uri,
    name: video.fileName,
    type: video.mimeType,
  } as unknown as Blob);
}

/** URL the video player can stream a backend-saved video from (GET /videos/{filename}). */
export function savedVideoUrl(filename: string): string | null {
  return API_URL ? `${API_URL}/videos/${encodeURIComponent(filename)}` : null;
}

/**
 * Save steps edited in the app: cuts moved, steps split or merged (PUT /dances/{id}/steps).
 * Returns the steps with fresh pace and body-part labels.
 */
export async function updateSteps(
  danceId: string,
  steps: { start_ms: number; end_ms: number; source: number | null }[],
  savedCount: number,
): Promise<DanceStep[]> {
  if (!API_URL) throw new Error('Connect the backend (EXPO_PUBLIC_API_URL) to save steps.');
  let response: Response;
  try {
    response = await fetch(`${API_URL}/dances/${encodeURIComponent(danceId)}/steps`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...(await authHeader()) },
      // source: which saved step (by position) each step continues, so it keeps its id; null for a new step.
      body: JSON.stringify({
        steps: steps.map(({ start_ms, end_ms, source }) => ({ start_ms, end_ms, source })),
        saved_count: savedCount,
      }),
    });
  } catch {
    throw new Error(unreachable());
  }
  const text = await response.text();
  if (!response.ok) throw new Error(errorMessage(text, response.status));
  return (JSON.parse(text) as { steps: DanceStep[] }).steps;
}

/** Comparison-only retry. Only legacy sessions missing CSVs fall back to uploads. */
const pendingRetries = new Map<string, Promise<AnalysisResult>>();

export function retryAnalysis(
  sessionId: string | undefined, mirrorMode: Exclude<MirrorMode, 'auto'>,
  reference?: PickedVideo | null, practice?: PickedVideo | null,
  onProgress?: (fraction: number) => void,
  step?: { start_ms: number; end_ms: number },
): Promise<AnalysisResult> {
  if (!sessionId) {
    if (reference && practice) return analyze(reference, practice, onProgress, step, mirrorMode);
    return Promise.reject(new Error('Select the original videos to retry this older analysis.'));
  }
  const key = `${sessionId}:${mirrorMode}`;
  const pending = pendingRetries.get(key);
  if (pending) return pending;
  const request = recompareAnalysis(sessionId, mirrorMode).catch((error: unknown) => {
    if (error instanceof MissingPoseDataError && reference && practice) {
      return analyze(reference, practice, onProgress, step, mirrorMode);
    }
    throw error;
  }).finally(() => pendingRetries.delete(key));
  pendingRetries.set(key, request);
  return request;
}

class MissingPoseDataError extends Error {}

export async function recompareAnalysis(sessionId: string, mirrorMode: Exclude<MirrorMode, 'auto'>): Promise<AnalysisResult> {
  if (mirrorMode !== 'same' && mirrorMode !== 'mirrored') throw new Error('Choose same or mirrored sides.');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);
  try {
    const response = await fetch(`${analysisUrl(sessionId)}/recompare`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ mirrorMode }), signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 409 && data.detail?.code === 'pose_data_missing') {
        throw new MissingPoseDataError(data.detail.message);
      }
      throw new Error(typeof data.detail === 'string' ? data.detail : data.error?.message ?? `Recomparison failed (${response.status}).`);
    }
    return data as AnalysisResult;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('Comparison timed out. Your previous results remain available.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function analysisUrl(sessionId: string): string {
  if (!API_URL) throw new Error('Saved analysis details require a connected backend.');
  if (!/^[0-9a-f]{32}$/.test(sessionId)) throw new Error('Invalid analysis session ID.');
  return `${API_URL.replace(/\/+$/, '')}/analyses/${sessionId}`;
}

/** Reads saved results; these requests never upload or analyze videos. */
export async function getAnalysis(sessionId: string): Promise<AnalysisResult> {
  return getAnalysisJson<AnalysisResult>(analysisUrl(sessionId));
}

export async function getCoaching(sessionId: string): Promise<CoachingConversation> {
  return getAnalysisJson<CoachingConversation>(`${analysisUrl(sessionId)}/coaching`);
}

/** Only session ID and question go to our backend; provider credentials stay there. */
export async function askCoach(sessionId: string, message?: string, requestId = 'initial'): Promise<CoachingConversation> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45_000);
  try {
    const response = await fetch(`${analysisUrl(sessionId)}/coaching`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ message, requestId }), signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? data.error?.message ?? 'Coaching is unavailable. Your comparison results are still available.');
    return data as CoachingConversation;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('AI coaching timed out. Retry coaching; your comparison results are still available.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function getAnalysisFrames(sessionId: string, offset = 0, limit = 50): Promise<FrameComparisonPage> {
  if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('Use a nonnegative offset and a page size from 1 to 100.');
  }
  return getAnalysisJson<FrameComparisonPage>(`${analysisUrl(sessionId)}/frames?offset=${offset}&limit=${limit}`);
}

/** Explicit opt-in to the large debugging download; the results screen does not fetch it. */
export function analysisDiagnosticsUrl(sessionId: string, download = true): string {
  return `${analysisUrl(sessionId)}/diagnostics?download=${download}`;
}

async function getAnalysisJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : data.error?.message ?? `Request failed (${response.status}).`);
  }
  return data as T;
}
