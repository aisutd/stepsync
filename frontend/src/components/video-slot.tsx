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
};

export function VideoSlot({ title, hint, video, onChoose, onRecord }: Props) {
  return (
    <View style={[styles.slot, video && styles.filled]}>
      <View style={styles.text}>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.hint} numberOfLines={1}>
          {video ? describe(video) : hint}
        </Text>
      </View>
      <View style={styles.actions}>
        {onRecord && <Action label="Record" onPress={onRecord} />}
        <Action label={video ? 'Change' : 'Choose'} onPress={onChoose} />
      </View>
    </View>
  );
}

function Action({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      style={({ pressed }) => [styles.action, pressed && styles.pressed]}
    >
      <Text style={styles.actionText}>{label}</Text>
    </Pressable>
  );
}

function describe(video: PickedVideo): string {
  if (video.durationMs == null) return video.fileName;
  return `${video.fileName} · ${(video.durationMs / 1000).toFixed(1)}s`;
}

const styles = StyleSheet.create({
  slot: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 16,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: 'dashed',
    backgroundColor: colors.surface,
  },
  filled: { borderStyle: 'solid', borderColor: colors.accent },
  text: { flex: 1, gap: 4 },
  title: { color: colors.text, fontSize: 17, fontWeight: '600' },
  hint: { color: colors.muted, fontSize: 14 },
  actions: { flexDirection: 'row', gap: 8 },
  action: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: colors.background,
  },
  pressed: { opacity: 0.6 },
  actionText: { color: colors.accent, fontSize: 15, fontWeight: '600' },
});
