import { Platform } from 'react-native';

import { mockAnalyze } from './mock';
import type { AnalysisResult, PickedVideo } from './types';

const API_URL = process.env.EXPO_PUBLIC_API_URL;

/** True until EXPO_PUBLIC_API_URL is set in .env. */
export const usingMockApi = !API_URL;

/**
 * Uploads both videos to POST /analyze and returns the feedback.
 * `onProgress` gets 0 to 1 as the upload goes; at 1 the server is analyzing.
 */
export async function analyze(
  reference: PickedVideo,
  practice: PickedVideo,
  onProgress?: (fraction: number) => void,
): Promise<AnalysisResult> {
  if (!API_URL) return mockAnalyze(practice);

  const body = new FormData();
  await appendVideo(body, 'reference', reference);
  await appendVideo(body, 'practice', practice);

  return postForm<AnalysisResult>(`${API_URL}/analyze`, body, onProgress);
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
          `Couldn't reach ${API_URL}. Is the backend running with --host 0.0.0.0, ` +
            'and is your phone on the same Wi-Fi?',
        ),
      );
    xhr.ontimeout = () => reject(new Error('The upload timed out.'));

    xhr.send(body);
  });
}

function serverError(xhr: XMLHttpRequest): string {
  try {
    const detail = JSON.parse(xhr.responseText)?.detail;
    if (typeof detail === 'string') return detail;
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
