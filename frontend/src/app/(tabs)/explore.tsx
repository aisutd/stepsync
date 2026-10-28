import { useCallback, useState } from 'react';
import { useFocusEffect, useRouter } from 'expo-router';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { getSavedDanceVideo, listSavedDances } from '@/api/client';
import { useSession } from '@/state/session';
import { colors } from '@/theme';

export default function ExploreScreen() {
  const router = useRouter();
  const { setReference } = useSession();
  const [dances, setDances] = useState<Awaited<ReturnType<typeof listSavedDances>>>([]);
  const [busy, setBusy] = useState(false);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useFocusEffect(useCallback(() => {
    let live = true;
    setBusy(true);
    listSavedDances().then(rows => { if (live) setDances(rows); })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, []));
  async function practice(dance: (typeof dances)[number]) {
    setSelecting(dance.id); setError(null);
    try {
      const uri = await getSavedDanceVideo(dance.id);
      setReference({ uri, fileName: `${dance.id}_skeleton.mp4`, mimeType: 'video/mp4', durationMs: dance.duration_ms,
        youtube: { url: '', videoId: '', isShort: false, title: dance.title,
          serverFilename: `${dance.id}_skeleton.mp4`, playbackUrl: uri, danceId: dance.id } });
      router.push('/practice');
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSelecting(null); }
  }
  return (
    <ScrollView style={styles.page} contentContainerStyle={styles.container}>
      <Text style={styles.title}>Your dance library</Text>
      <Text style={styles.subtitle}>Imported dances saved under your account. Select one to practice with DTW.</Text>
      {busy && <ActivityIndicator color={colors.text} />}
      {error && <Text style={styles.error}>{error}</Text>}
      {!busy && dances.length === 0 && <Text style={styles.subtitle}>No saved dances yet. Import one from Home.</Text>}
      {dances.map(d => <Pressable key={d.id} style={styles.card} onPress={() => practice(d)} disabled={selecting !== null}>
        <Text style={styles.name}>{d.title}</Text>
        <Text style={styles.subtitle}>{d.status} · {Math.round((d.duration_ms || 0)/1000)} seconds</Text>
        <Text style={styles.link}>{selecting === d.id ? 'Opening video…' : 'Practice this dance →'}</Text>
      </Pressable>)}
    </ScrollView>
  );
}
const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.background },
  container: { padding: 24, paddingBottom: 120, gap: 16 },
  title: { color: colors.text, fontSize: 26, fontWeight: '700' },
  subtitle: { color: colors.muted, fontSize: 14 },
  card: { backgroundColor: colors.surface, borderRadius: 16, padding: 18, gap: 8 },
  name: { color: colors.text, fontSize: 18, fontWeight: '600' },
  link: { color: colors.accent, fontSize: 14, fontWeight: '600' },
  error: { color: '#c0392b' },
});
