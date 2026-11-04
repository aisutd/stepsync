import { Platform } from 'react-native';

import { supabase, supabaseConfigured } from '@/lib/supabase';

import { mockAnalyze } from './mock';
import type { AnalysisResult, CoachingConversation, FrameComparisonPage, MirrorMode, PickedVideo, YouTubeImportResponse, DanceStep } from './types';

const API_URL = process.env.EXPO_PUBLIC_API_URL;

/** True until EXPO_PUBLIC_API_URL is set in .env. */
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
  step?: DanceStep,
): Promise<AnalysisResult> {
  if (!API_URL) throw new Error('Set EXPO_PUBLIC_API_URL to use real DTW analysis.');

  const body = new FormData();
  if (step) {
    if (!Number.isFinite(step.start_ms) || !Number.isFinite(step.end_ms) || step.end_ms <= step.start_ms) {
      throw new Error('Invalid tutorial step range.');
    }
    body.append('step_start_ms', String(Math.round(step.start_ms)));
    body.append('step_end_ms', String(Math.round(step.end_ms)));
  }
  if (reference.youtube?.danceId) {
    // Saved YouTube reference stays server-side. Only upload the practice take.
    await appendVideo(body, 'practice', practice);
    return postForm<AnalysisResult>(
      `${API_URL}/dances/${encodeURIComponent(reference.youtube.danceId)}/analyze-dtw`,
      body, onProgress,
    );
  }
  await appendVideo(body, 'reference', reference);
  await appendVideo(body, 'practice', practice);
  return postForm<AnalysisResult>(`${API_URL}/analyze-dtw`, body, onProgress);
}

/**
 * Asks the backend to download a YouTube video or Short (POST /reference-videos).
 * The backend also runs pose extraction before answering, so this can take minutes.
 */
export async function importYouTube(url: string): Promise<YouTubeImportResponse> {
  if (!API_URL) throw new Error('Configure EXPO_PUBLIC_API_URL to import videos.');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12 * 60 * 1000);
  try {
    const response = await fetch(`${API_URL}/dances/import-youtube`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await authHeader()) },
      body: JSON.stringify({ url }),
      signal: controller.signal,
    });
    const text = await response.text();
    if (!response.ok) throw new Error(errorMessage(text, response.status));
    const imported = JSON.parse(text) as {
      dance_id: string; frames: number; keyframes: number;
      steps?: number; duration_ms?: number;
    };
    // Signed URL returned only after the user's JWT/RLS validates dance access.
    const playback = await fetch(`${API_URL}/dances/${encodeURIComponent(imported.dance_id)}/video-url`, {
      headers: await authHeader(),
    });
    if (!playback.ok) throw new Error(errorMessage(await playback.text(), playback.status));
    const video = await playback.json() as { url?: string; signed_url?: string; video_url?: string };
    const playbackUrl = video.url || video.signed_url || video.video_url;
    if (!playbackUrl) throw new Error('Server returned no video playback URL.');
    const detailsResponse = await fetch(`${API_URL}/dances/${encodeURIComponent(imported.dance_id)}`, {
      headers: await authHeader(),
    });
    if (!detailsResponse.ok) throw new Error(errorMessage(await detailsResponse.text(), detailsResponse.status));
    const details = await detailsResponse.json() as {
      dance: { title: string; duration_ms?: number };
      steps: Array<{ step_order: number; name: string; start_ms: number; end_ms: number }>;
    };
    return {
      status: 'completed', source_url: playbackUrl,
      filename: `${imported.dance_id}_skeleton.mp4`, size_bytes: 0,
      metadata: { duration_seconds: (details.dance.duration_ms || imported.duration_ms || 0) / 1000, width: 0, height: 0, fps: 0 },
      pose_processing: 'completed', persisted: true,
      supabase_status: 'saved', supabase_dance_id: imported.dance_id,
      frames_saved: imported.frames,
      steps: details.steps.map((step, index) => ({
        step_index: index, label: step.name, start_ms: step.start_ms,
        end_ms: step.end_ms, intensity: 'medium' as const, focus: [] as ('arms'|'legs'|'head'|'torso')[],
      })),
    };
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') throw new Error('Import timed out; try a shorter public video.');
    if (e instanceof TypeError) throw new Error(unreachable());
    throw e;
  } finally { clearTimeout(timer); }
}

async function authHeader(): Promise<Record<string, string>> {
  if (!supabaseConfigured) throw new Error('Configure Supabase and sign in first.');
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

    authHeader().then(headers => {
      if (!headers.Authorization) { reject(new Error('Log in before analyzing your dance.')); return; }
      xhr.setRequestHeader('Authorization', headers.Authorization);
      xhr.send(body);
    }).catch(reject);
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

/** Real Supabase library, filtered by database RLS through the caller's JWT. */
export type SavedDance = { id: string; title: string; duration_ms: number; status: string; video_path?: string };
export async function listSavedDances(): Promise<SavedDance[]> {
  if (!API_URL) throw new Error('Connect the backend to see your imported dances.');
  const response = await fetch(`${API_URL}/tables/dances?select=id,title,duration_ms,status,video_path`, { headers: await authHeader() });
  if (!response.ok) throw new Error(errorMessage(await response.text(), response.status));
  return ((await response.json()) as {rows: SavedDance[]}).rows.reverse();
}
export async function getSavedDanceVideo(id: string): Promise<string> {
  if (!API_URL) throw new Error('Backend URL not configured.');
  const response = await fetch(`${API_URL}/dances/${encodeURIComponent(id)}/video-url`, { headers: await authHeader() });
  if (!response.ok) throw new Error(errorMessage(await response.text(), response.status));
  const json = await response.json() as {url?: string};
  if (!json.url) throw new Error('No skeleton MP4 saved for this dance.');
  return json.url;
}


function analysisUrl(sessionId: string): string {
  if (!API_URL) throw new Error('Saved analysis details require a connected backend.');
  if (!/^[0-9a-f]{32}$/.test(sessionId)) throw new Error('Invalid analysis session ID.');
  return `${API_URL.replace(/\/+$/, '')}/analyses/${sessionId}`;
}

/** Reads saved results; these requests never upload or analyze videos. */
export async function getAnalysis(sessionId: string): Promise<AnalysisResult> {
  return getJson<AnalysisResult>(analysisUrl(sessionId));
}

export async function getCoaching(sessionId: string): Promise<CoachingConversation> {
  return getJson<CoachingConversation>(`${analysisUrl(sessionId)}/coaching`);
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
  return getJson<FrameComparisonPage>(`${analysisUrl(sessionId)}/frames?offset=${offset}&limit=${limit}`);
}

/** Explicit opt-in to the large debugging download; the results screen does not fetch it. */
export function analysisDiagnosticsUrl(sessionId: string, download = true): string {
  return `${analysisUrl(sessionId)}/diagnostics?download=${download}`;
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : data.error?.message ?? `Request failed (${response.status}).`);
  }
  return data as T;
}


/** Rodrigo's coverage-aware pose comparison and AI-coaching pipeline.
 * Independent from authenticated Supabase /analyze-dtw.
 */
export async function analyzeDetailed(
  reference: PickedVideo, practice: PickedVideo,
  onProgress?: (fraction: number) => void, mirrorMode: MirrorMode = 'auto',
): Promise<AnalysisResult> {
  if (!API_URL) throw new Error('Configure EXPO_PUBLIC_API_URL first.');
  if (reference.youtube) throw new Error('Detailed comparison currently requires a local reference video. Use DTW for imported YouTube dances.');
  const body = new FormData();
  await appendVideo(body, 'reference', reference);
  await appendVideo(body, 'practice', practice);
  body.append('mirror_mode', mirrorMode);
  return postForm<AnalysisResult>(`${API_URL}/analyze`, body, onProgress);
}

/** Read the precise step boundaries of a saved tutorial before comparison. */
export async function getSavedDanceSteps(id: string): Promise<DanceStep[]> {
  if (!API_URL) throw new Error('Backend URL not configured.');
  const response = await fetch(`${API_URL}/dances/${encodeURIComponent(id)}`, { headers: await authHeader() });
  if (!response.ok) throw new Error(errorMessage(await response.text(), response.status));
  const json = await response.json() as { steps?: { step_order: number; name: string; start_ms: number; end_ms: number }[] };
  return (json.steps ?? []).map((step, i) => ({
    step_index: i, label: step.name || `Step ${i + 1}`,
    start_ms: step.start_ms, end_ms: step.end_ms, intensity: 'medium', focus: [],
  })).filter(step => Number.isFinite(step.start_ms) && Number.isFinite(step.end_ms) && step.end_ms > step.start_ms);
}
