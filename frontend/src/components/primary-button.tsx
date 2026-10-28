import Ionicons from '@expo/vector-icons/Ionicons';
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type ViewStyle, type StyleProp, type TextStyle } from 'react-native';

import { colors, radius } from '@/theme';

type Props = {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  /** Arrow on the right, as in the Figma buttons. */
  arrow?: boolean;
  style?: ViewStyle;
  labelStyle?: StyleProp<TextStyle>;
  trailingIcon?: ReactNode;
};

export function PrimaryButton({ label, onPress, loading, disabled, arrow = true, style, labelStyle, trailingIcon }: Props) {
  const inactive = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      disabled={inactive}
      style={({ pressed }) => [styles.button, disabled && !loading && styles.disabled, pressed && styles.pressed, style]}
    >
      {loading ? (
        <ActivityIndicator color={colors.onPrimary} />
      ) : (
        <View style={styles.row}>
          <Text style={[styles.label, labelStyle]}>{label}</Text>
          {trailingIcon ?? (arrow && <Ionicons name="arrow-forward" size={20} color={colors.onPrimary} style={styles.arrow} />)}
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    height: 54,
    borderRadius: radius.md,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    paddingHorizontal: 22,
  },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  label: { color: colors.onPrimary, fontSize: 17, fontWeight: '600' },
  arrow: { position: 'absolute', right: 0 },
  disabled: { opacity: 0.45 },
  pressed: { opacity: 0.85 },
});
