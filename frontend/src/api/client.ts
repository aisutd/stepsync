import { Platform } from 'react-native';

import { mockAnalyze } from './mock';
import type { AnalysisResult, CoachingConversation, FrameComparisonPage, MirrorMode, PickedVideo } from './types';

const API_URL = (process.env.EXPO_PUBLIC_API_URL || (Platform.OS === 'web' ? 'http://127.0.0.1:8000' : undefined))?.replace(/\/+$/, '');

/** Native previews can use sample data; browser sessions connect to the local backend by default. */
export const usingMockApi = !API_URL;

/**
 * Uploads both videos to POST /analyze and returns the feedback.
 * `onProgress` gets 0 to 1 as the upload goes; at 1 the server is analyzing.
 */
export async function analyze(
  reference: PickedVideo,
  practice: PickedVideo,
  onProgress?: (fraction: number) => void,
  mirrorMode: MirrorMode = 'auto',
): Promise<AnalysisResult> {
  if (!API_URL) return mockAnalyze(practice);

  const body = new FormData();
  await appendVideo(body, 'reference', reference);
  await appendVideo(body, 'practice', practice);
  body.append('mirror_mode', mirrorMode);

  return postForm<AnalysisResult>(`${API_URL}/analyze`, body, onProgress);
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
    // Allow both pose extractors their ten-minute deadlines, plus upload/comparison time.
    xhr.timeout = 25 * 60 * 1000;

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.upload.onload = () => onProgress?.(1);
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(serverError(xhr)));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch {
        reject(new Error('The server sent back something that is not JSON.'));
      }
    };
    xhr.onerror = () =>
      reject(
        new Error(
          `Couldn't reach ${API_URL}. Start the backend and check the API URL. ` +
            (Platform.OS === 'web' ? 'For local browser testing, run .\\run-local.ps1 in the project folder.' : 'Use the LAN IP of your computer and connect your phone to the same Wi-Fi.'),
        ),
      );
    xhr.ontimeout = () => reject(new Error('Analysis timed out. Try shorter videos and check the backend terminal before retrying.'));

    xhr.send(body);
  });
}

function serverError(xhr: XMLHttpRequest): string {
  try {
    const data = JSON.parse(xhr.responseText);
    if (typeof data.detail === 'string') return data.detail;
    if (typeof data.error?.message === 'string') return data.error.message;
    if (Array.isArray(data.detail)) return data.detail.map((item: { msg?: string }) => item.msg ?? 'Invalid upload').join('; ');
  } catch {
    // fall through to the generic message
  }
  return `Upload failed (${xhr.status}).`;
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
