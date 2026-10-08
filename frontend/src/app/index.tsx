import * as ImagePicker from 'expo-image-picker';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text } from 'react-native';

import { analyze, usingMockApi } from '@/api/client';
import type { PickedVideo } from '@/api/types';
import { VideoSlot } from '@/components/video-slot';
import { useSession } from '@/state/session';
import { colors } from '@/theme';

export default function HomeScreen() {
  const router = useRouter();
  const { reference, practice, setReference, setPractice, setResult } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = reference !== null && practice !== null && !loading;

  async function onAnalyze() {
    if (!reference || !practice) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await analyze(reference, practice));
      router.push('/results');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.lead}>
        Pick the routine you are learning and a take of you dancing it.
      </Text>

      <VideoSlot
        title="Reference video"
        hint="The choreography you want to match"
        video={reference}
        onPress={async () => setReference((await pickVideo()) ?? reference)}
      />
      <VideoSlot
        title="Practice video"
        hint="Your attempt"
        video={practice}
        onPress={async () => setPractice((await pickVideo()) ?? practice)}
      />

      <Pressable
        onPress={onAnalyze}
        disabled={!ready}
        style={({ pressed }) => [styles.button, !ready && styles.disabled, pressed && styles.pressed]}
      >
        {loading ? (
          <ActivityIndicator color={colors.text} />
        ) : (
          <Text style={styles.buttonText}>Analyze</Text>
        )}
      </Pressable>

      {error && <Text style={styles.error}>{error}</Text>}
      {usingMockApi && (
        <Text style={styles.note}>Mock mode: feedback is sample data, nothing is uploaded.</Text>
      )}
    </ScrollView>
  );
}

async function pickVideo(): Promise<PickedVideo | null> {
  const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['videos'] });
  if (picked.canceled) return null;

  const asset = picked.assets[0];
  return {
    uri: asset.uri,
    fileName: asset.fileName ?? asset.uri.split('/').pop() ?? 'video.mp4',
    mimeType: asset.mimeType ?? 'video/mp4',
    durationMs: asset.duration ?? null,
  };
}

const styles = StyleSheet.create({
  container: { padding: 20, gap: 16 },
  lead: { color: colors.muted, fontSize: 16, lineHeight: 22, marginBottom: 4 },
  button: {
    height: 52,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.accent,
    marginTop: 8,
  },
  disabled: { opacity: 0.4 },
  pressed: { opacity: 0.8 },
  buttonText: { color: colors.text, fontSize: 17, fontWeight: '600' },
  error: { color: colors.bad, fontSize: 14 },
  note: { color: colors.muted, fontSize: 13, textAlign: 'center' },
});
