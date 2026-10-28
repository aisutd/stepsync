// Mirrors validate_url in backend/app/youtube.py so the app accepts exactly
// what the backend accepts: watch, youtu.be and Shorts links, no playlists.

export type ParsedYouTube = { videoId: string; isShort: boolean };

const HOSTS = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be']);
const ID = /^[A-Za-z0-9_-]{11}$/;

export function parseYouTubeUrl(input: string): ParsedYouTube | { error: string } {
  let raw = input.trim();
  if (!raw) return { error: '' };
  // People often paste links without the scheme.
  if (!/^https?:\/\//i.test(raw)) raw = `https://${raw}`;

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { error: "That doesn't look like a link." };
  }
  const host = url.hostname.toLowerCase();
  if (!HOSTS.has(host)) return { error: 'Only YouTube links are supported.' };
  if (url.searchParams.has('list')) {
    return { error: "Playlist links aren't supported. Open the single video and copy its link." };
  }

  let videoId = '';
  let isShort = false;
  if (host.endsWith('youtu.be')) {
    videoId = url.pathname.replace(/^\//, '');
  } else if (url.pathname === '/watch') {
    const ids = url.searchParams.getAll('v');
    videoId = ids.length === 1 ? ids[0] : '';
  } else {
    const match = url.pathname.match(/^\/shorts\/([A-Za-z0-9_-]{11})\/?$/);
    if (match) {
      videoId = match[1];
      isShort = true;
    }
  }

  if (!ID.test(videoId)) return { error: 'Use a YouTube video or Shorts link.' };
  return { videoId, isShort };
}

export function youtubeThumbnail(videoId: string): string {
  return `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
}
