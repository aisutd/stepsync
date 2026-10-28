import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PickedVideo } from '@/api/types';
import { colors } from '@/theme';

type Props = {
  title: string;
  hint: string;
  video: PickedVideo | null;
  onChoose: () => void;
  /** Omit to hide the Record button (for example on web). */
  onRecord?: () => void;
  /** Omit to hide the YouTube button. */
  onYouTube?: () => void;
};

export function VideoSlot({ title, hint, video, onChoose, onRecord, onYouTube }: Props) {
  return (
    <View style={[styles.slot, video && styles.filled]}>
      <View style={styles.text}>
        <Text style={styles.title}>{title}</Text>
        <View style={styles.hintRow}>
          {video?.youtube && <Ionicons name="logo-youtube" size={15} color={colors.bad} />}
          <Text style={styles.hint} numberOfLines={1}>
            {video ? describe(video) : hint}
          </Text>
        </View>
        {video?.youtube?.poseWarning && (
          <Text style={styles.warning}>Saved, but pose extraction failed: {video.youtube.poseWarning}</Text>
        )}
      </View>
      <View style={styles.actions}>
        {onRecord && <Action icon="videocam-outline" label="Record" onPress={onRecord} />}
        <Action icon="images-outline" label={video && !video.youtube ? 'Change' : 'Choose'} onPress={onChoose} />
        {onYouTube && <Action icon="logo-youtube" label="YouTube" onPress={onYouTube} />}
      </View>
    </View>
  );
}

function Action({
  icon,
  label,
  onPress,
}: {
  icon: React.ComponentProps<typeof Ionicons>['name'];
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => [styles.action, pressed && styles.pressed]}
    >
      <Ionicons name={icon} size={16} color={colors.accent} />
      <Text style={styles.actionText}>{label}</Text>
    </Pressable>
  );
}

function describe(video: PickedVideo): string {
  const name = video.youtube ? video.youtube.title : video.fileName;
  if (video.durationMs == null) return name;
  return `${name} · ${(video.durationMs / 1000).toFixed(1)}s`;
}

const styles = StyleSheet.create({
  slot: {
    gap: 12,
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: 'dashed',
    backgroundColor: colors.surface,
  },
  filled: { borderStyle: 'solid', borderColor: colors.accentSoft },
  text: { gap: 4 },
  title: { color: colors.text, fontSize: 17, fontWeight: '600' },
  hintRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  hint: { flex: 1, color: colors.muted, fontSize: 14 },
  warning: { color: colors.okay, fontSize: 13, lineHeight: 18 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  action: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: colors.pill,
  },
  pressed: { opacity: 0.6 },
  actionText: { color: colors.accent, fontSize: 15, fontWeight: '600' },
});
