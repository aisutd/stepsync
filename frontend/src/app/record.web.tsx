/** Browser camera recording. Native uses the separate record.tsx screen. */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSession } from '@/state/session';
import { colors } from '@/theme';

const MAX_DURATION_MS = 180_000;
export default function RecordWebScreen() {
  const router = useRouter();
  const { slot } = useLocalSearchParams<{ slot?: string }>();
  const { setPractice, setReference } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [ready, setReady] = useState(false);
  const preview = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const started = useRef(0);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = useRef(true);
  const saveVideo = useRef(slot === 'reference' ? setReference : setPractice);
  saveVideo.current = slot === 'reference' ? setReference : setPractice;

  useEffect(() => {
    active.current = true;
    let cancelled = false;
    const startCamera = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
          throw new Error('This browser does not support camera recording. Use Chrome or Edge on localhost, or choose a saved video.');
        }
        const media = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: true })
          .catch(async () => navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false }));
        if (cancelled) { media.getTracks().forEach(track => track.stop()); return; }
        stream.current = media;
        if (preview.current) { preview.current.srcObject = media; void preview.current.play().catch(() => {}); }
        setReady(true);
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : 'Camera is unavailable.'); }
    };
    void startCamera();
    return () => {
      cancelled = true; active.current = false;
      if (timeout.current) clearTimeout(timeout.current);
      if (recorder.current?.state === 'recording') recorder.current.stop();
      stream.current?.getTracks().forEach(track => track.stop());
    };
  }, []);

  function beginRecording() {
    if (!stream.current || recording) return;
    try {
      const format = ['video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'].find(t => MediaRecorder.isTypeSupported(t));
      if (!format) throw new Error('This browser cannot record a supported video format. Use a saved MP4 instead.');
      const rec = new MediaRecorder(stream.current, { mimeType: format });
      const items: Blob[] = [];
      chunks.current = items;
      started.current = Date.now();
      rec.ondataavailable = event => { if (event.data.size) items.push(event.data); };
      rec.onerror = () => { if (active.current) setError('Recording failed. Try another browser or upload a video.'); };
      rec.onstop = () => {
        if (timeout.current) clearTimeout(timeout.current);
        if (!active.current) return;
        setRecording(false);
        if (!items.length) { setError('No video was recorded. Try again.'); return; }
        const blob = new Blob(items, { type: format });
        const uri = URL.createObjectURL(blob);
        saveVideo.current({ uri, fileName: `practice-${Date.now()}.${format.includes('mp4') ? 'mp4' : 'webm'}`, mimeType: format.includes('mp4') ? 'video/mp4' : 'video/webm', durationMs: Date.now() - started.current });
        stream.current?.getTracks().forEach(track => track.stop());
        router.back();
      };
      rec.start(500);
      recorder.current = rec;
      setRecording(true);
      timeout.current = setTimeout(() => { if (rec.state === 'recording') rec.stop(); }, MAX_DURATION_MS);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start recording.'); }
  }
  function stopRecording() { if (recorder.current?.state === 'recording') recorder.current.stop(); }
  return <View style={styles.page}>
    <Text style={styles.heading}>Record {slot === 'reference' ? 'tutorial' : 'practice'}</Text>
    <Text style={styles.help}>Allow camera permission. Keep your whole body visible. Press Stop when you finish your step.</Text>
    {error && <Text style={styles.error}>{error}</Text>}
    <video ref={preview} autoPlay muted playsInline style={{ width: '100%', maxHeight: 450, background: '#111', borderRadius: 14, transform: 'scaleX(-1)' }} />
    <Pressable disabled={!ready} onPress={recording ? stopRecording : beginRecording} style={[styles.button, !ready && styles.disabled]}>
      <Text style={styles.buttonText}>{recording ? '■ Stop and use recording' : '● Start recording'}</Text>
    </Pressable>
    <Pressable onPress={() => router.back()} style={styles.cancel}><Text style={styles.cancelText}>Cancel</Text></Pressable>
  </View>;
}
const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.background, padding: 24, gap: 18 },
  heading: { color: colors.text, fontWeight: '700', fontSize: 24 },
  help: { color: colors.muted, lineHeight: 20 },
  error: { color: colors.bad },
  button: { padding: 18, borderRadius: 12, backgroundColor: '#B32632', alignItems: 'center' },
  buttonText: { color: '#fff', fontSize: 17, fontWeight: '700' },
  disabled: { opacity: .5 },
  cancel: { alignItems: 'center', padding: 10 },
  cancelText: { color: colors.text },
});
