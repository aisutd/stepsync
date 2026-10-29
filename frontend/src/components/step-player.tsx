import Ionicons from '@expo/vector-icons/Ionicons';
import { useEvent } from 'expo';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useEffect, useRef, useState } from 'react';
import { Image, Pressable, StyleSheet, Switch, Text, View } from 'react-native';

import type { DanceStep } from '@/api/types';
import { colors, radius } from '@/theme';

type Props = {
  /** Streamable video URL; null shows the thumbnail only (mock mode). */
  source: string | null;
  thumbnail: string;
  steps: DanceStep[];
  durationMs: number | null;
};

const SEGMENT_COLORS = { slow: '#E3CDB6', medium: colors.accentSoft, fast: colors.accent } as const;
const INTENSITY = { slow: 'Slow', medium: 'Medium', fast: 'Fast' } as const;
// Treat times this close to a boundary as being on it (players report time in ~0.1 s steps).
const EPSILON = 0.06;

/**
 * Video preview of an uploaded dance with its segmentation: a timeline marks where each step
 * starts and stops, tapping a step plays just that step, and "Pause after each step" stops the
 * video at every boundary so the dancer can practice one step at a time.
 */
export function StepPlayer({ source, thumbnail, steps, durationMs }: Props) {
  const player = useVideoPlayer(source, (p) => {
    p.timeUpdateEventInterval = 0.05;
    p.loop = false;
  });
  const { currentTime } = useEvent(player, 'timeUpdate', {
    currentTime: 0,
    currentLiveTimestamp: null,
    currentOffsetFromLive: null,
    bufferedPosition: 0,
  });
  const { isPlaying } = useEvent(player, 'playingChange', { isPlaying: false });

  const [pauseEachStep, setPauseEachStep] = useState(true);
  const stopAt = useRef<number | null>(null);
  // After stopping at a boundary the video sits on the next step's first frame;
  // keep showing the step that just finished until playback resumes.
  const [heldStep, setHeldStep] = useState<number | null>(null);

  const totalSeconds = Math.max(
    (durationMs ?? 0) / 1000,
    player.duration || 0,
    steps.length ? steps[steps.length - 1].end_ms / 1000 : 0,
    0.001,
  );
  const stepAt = (t: number) => steps.findIndex((s) => t + EPSILON >= s.start_ms / 1000 && t + EPSILON < s.end_ms / 1000);
  const playingStep = stepAt(currentTime);
  const active = !isPlaying && heldStep !== null ? heldStep : playingStep;

  // Stop at the end of the current step, either because one step was tapped
  // or because "Pause after each step" is on.
  useEffect(() => {
    if (!source || !isPlaying) return;
    if (heldStep !== null) setHeldStep(null);
    if (stopAt.current === null && pauseEachStep && playingStep >= 0) {
      stopAt.current = steps[playingStep].end_ms / 1000;
    }
    if (stopAt.current !== null && currentTime >= stopAt.current - EPSILON) {
      const boundary = stopAt.current;
      const finished = steps.findIndex((step) => Math.abs(step.end_ms / 1000 - boundary) < 0.001);
      player.pause();
      setHeldStep(finished >= 0 ? finished : null);
      // Land exactly on the boundary so the next play continues with the next step.
      player.currentTime = stopAt.current;
      stopAt.current = null;
    }
  }, [currentTime, isPlaying, pauseEachStep, playingStep, heldStep, source, steps, player]);

  function playStep(index: number) {
    if (!source) return;
    const step = steps[index];
    player.currentTime = step.start_ms / 1000;
    stopAt.current = step.end_ms / 1000;
    player.play();
  }

  function togglePlay() {
    if (!source) return;
    if (isPlaying) {
      player.pause();
      return;
    }
    // At the very end, start over.
    if (currentTime >= totalSeconds - EPSILON) player.currentTime = 0;
    stopAt.current = null;
    player.play();
  }

  function restart() {
    if (!source) return;
    setHeldStep(null);
    player.pause();
    stopAt.current = null;
    player.currentTime = 0;
  }

  const firstStart = steps.length ? steps[0].start_ms / 1000 : 0;
  const lastEnd = steps.length ? steps[steps.length - 1].end_ms / 1000 : 0;
  const pct = (seconds: number) => `${Math.min(100, Math.max(0, (seconds / totalSeconds) * 100))}%` as const;

  return (
    <View style={styles.container}>
      <View style={styles.video}>
        {source ? (
          // Explicit 100% size: on web a <video> ignores absolute edges and keeps its own size.
          <VideoView player={player} style={styles.videoView} contentFit="contain" nativeControls={false} />
        ) : (
          <Image source={{ uri: thumbnail }} style={StyleSheet.absoluteFill} resizeMode="cover" />
        )}
        {active >= 0 && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>
              Step {active + 1} of {steps.length}
            </Text>
          </View>
        )}
      </View>

      {steps.length > 0 && (
        <View>
          {/* Timeline: one segment per step; the gaps between segments are the stop points. */}
          <View style={styles.timeline} accessibilityLabel={`Timeline with ${steps.length} steps`}>
            {firstStart > 0 && <View style={[styles.filler, { width: pct(firstStart) }]} />}
            {steps.map((step, index) => (
              <Pressable
                key={step.step_index}
                onPress={() => playStep(index)}
                accessibilityLabel={`Play step ${index + 1}`}
                style={[
                  styles.segment,
                  {
                    width: pct((step.end_ms - step.start_ms) / 1000),
                    backgroundColor: SEGMENT_COLORS[step.intensity],
                  },
                  index === active && styles.activeSegment,
                ]}
              />
            ))}
            {lastEnd < totalSeconds && <View style={[styles.filler, { flex: 1 }]} />}
            {source && <View pointerEvents="none" style={[styles.playhead, { left: pct(currentTime) }]} />}
          </View>
          <View style={styles.timeRow}>
            <Text style={styles.time}>{formatSeconds(currentTime * 1000)}</Text>
            <Text style={styles.time}>{formatSeconds(totalSeconds * 1000)}</Text>
          </View>
        </View>
      )}

      {source && (
        <View style={styles.controls}>
          <Pressable onPress={restart} hitSlop={8} accessibilityLabel="Back to start" style={styles.iconButton}>
            <Ionicons name="play-skip-back" size={18} color={colors.text} />
          </Pressable>
          <Pressable onPress={togglePlay} accessibilityLabel={isPlaying ? 'Pause' : 'Play'} style={styles.playButton}>
            <Ionicons name={isPlaying ? 'pause' : 'play'} size={22} color={colors.onPrimary} />
          </Pressable>
          <View style={styles.toggle}>
            <Text style={styles.toggleText}>Pause after each step</Text>
            <Switch
              value={pauseEachStep}
              onValueChange={(on) => {
                setPauseEachStep(on);
                stopAt.current = null;
              }}
              trackColor={{ true: colors.accentSoft, false: colors.hairline }}
              thumbColor={colors.surface}
            />
          </View>
        </View>
      )}

      <View style={styles.steps}>
        {steps.map((step, index) => {
          const focus = step.focus.map((part) => part[0].toUpperCase() + part.slice(1)).join(' + ');
          const current = index === active;
          return (
            <Pressable
              key={step.step_index}
              onPress={() => playStep(index)}
              disabled={!source}
              style={({ pressed }) => [styles.stepRow, current && styles.stepRowActive, pressed && styles.pressed]}
            >
              <View style={[styles.stepNumber, current && styles.stepNumberActive]}>
                <Text style={[styles.stepNumberText, current && styles.stepNumberTextActive]}>{index + 1}</Text>
              </View>
              <View style={styles.stepText}>
                <Text style={styles.stepTime}>
                  {formatSeconds(step.start_ms)} to {formatSeconds(step.end_ms)}
                </Text>
                <Text style={styles.stepDetail}>
                  {INTENSITY[step.intensity]}
                  {focus ? ` · ${focus}` : ''}
                </Text>
              </View>
              {source && (
                <Ionicons name={current && isPlaying ? 'pause-circle' : 'play-circle'} size={26} color={colors.accent} />
              )}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

// Steps are short, so show tenths: 1.5s, 1:02.3
export function formatSeconds(ms: number): string {
  const total = ms / 1000;
  const minutes = Math.floor(total / 60);
  const rest = (total - minutes * 60).toFixed(1);
  return minutes > 0 ? `${minutes}:${rest.padStart(4, '0')}` : `${rest}s`;
}

const styles = StyleSheet.create({
  container: { gap: 12 },
  video: { height: 360, borderRadius: radius.md, overflow: 'hidden', backgroundColor: colors.primary },
  videoView: { width: '100%', height: '100%' },
  badge: {
    position: 'absolute',
    left: 10,
    top: 10,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  badgeText: { color: colors.onPrimary, fontSize: 13, fontWeight: '600' },
  timeline: { flexDirection: 'row', height: 22, gap: 2, alignItems: 'stretch' },
  filler: { backgroundColor: colors.hairline, borderRadius: 4 },
  segment: { borderRadius: 4 },
  activeSegment: { borderWidth: 2, borderColor: colors.text },
  playhead: { position: 'absolute', top: -4, bottom: -4, width: 3, marginLeft: -1.5, borderRadius: 2, backgroundColor: colors.text },
  timeRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  time: { color: colors.muted, fontSize: 12, fontVariant: ['tabular-nums'] },
  controls: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  iconButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
  },
  playButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.primary,
    paddingLeft: 2,
  },
  toggle: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 8 },
  toggleText: { color: colors.text, fontSize: 13, flexShrink: 1, textAlign: 'right' },
  steps: { gap: 8 },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: radius.sm,
    borderWidth: 1.5,
    borderColor: 'transparent',
    backgroundColor: colors.surface,
  },
  stepRowActive: { borderColor: colors.accentSoft },
  pressed: { opacity: 0.7 },
  stepNumber: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberActive: { backgroundColor: colors.accent },
  stepNumberText: { color: colors.pillText, fontSize: 13, fontWeight: '700' },
  stepNumberTextActive: { color: colors.onPrimary },
  stepText: { flex: 1, gap: 1 },
  stepTime: { color: colors.text, fontSize: 14, fontWeight: '600', fontVariant: ['tabular-nums'] },
  stepDetail: { color: colors.muted, fontSize: 13 },
});
