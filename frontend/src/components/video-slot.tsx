import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PickedVideo } from '@/api/types';
import { colors } from '@/theme';

type Props = {
  title: string;
  hint: string;
  video: PickedVideo | null;
  onPress: () => void;
};

export function VideoSlot({ title, hint, video, onPress }: Props) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.slot, video && styles.filled, pressed && styles.pressed]}
    >
      <View style={styles.text}>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.hint} numberOfLines={1}>
          {video ? describe(video) : hint}
        </Text>
      </View>
      <Text style={styles.action}>{video ? 'Change' : 'Choose'}</Text>
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
  pressed: { opacity: 0.7 },
  text: { flex: 1, gap: 4 },
  title: { color: colors.text, fontSize: 17, fontWeight: '600' },
  hint: { color: colors.muted, fontSize: 14 },
  action: { color: colors.accent, fontSize: 15, fontWeight: '600' },
});
