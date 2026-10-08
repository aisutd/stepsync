import { Platform } from 'react-native';

import { mockAnalyze } from './mock';
import type { AnalysisResult, PickedVideo } from './types';

const API_URL = process.env.EXPO_PUBLIC_API_URL;

/** True until EXPO_PUBLIC_API_URL is set in .env. */
export const usingMockApi = !API_URL;

export async function analyze(
  reference: PickedVideo,
  practice: PickedVideo,
): Promise<AnalysisResult> {
  if (!API_URL) return mockAnalyze(practice);

  const body = new FormData();
  await appendVideo(body, 'reference', reference);
  await appendVideo(body, 'practice', practice);

  const response = await fetch(`${API_URL}/analyze`, { method: 'POST', body });
  if (!response.ok) {
    throw new Error(`Analysis failed (${response.status})`);
  }
  return (await response.json()) as AnalysisResult;
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
