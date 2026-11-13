import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius } from '@/theme';

type IconName = ComponentProps<typeof Ionicons>['name'];

export type SheetAction = { label: string; icon: IconName; destructive?: boolean; onPress: () => void };

/** A menu that slides up from the bottom (the "⋯" menu). Works the same on the phone and the web. */
export function ActionSheet({
  visible,
  title,
  actions,
  onClose,
}: {
  visible: boolean;
  title?: string;
  actions: SheetAction[];
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close menu">
        <Pressable style={[styles.sheet, { paddingBottom: Math.max(16, insets.bottom + 8) }]} onPress={() => {}}>
          {title && (
            <Text style={styles.sheetTitle} numberOfLines={1}>
              {title}
            </Text>
          )}
          {actions.map((action) => (
            <Pressable
              key={action.label}
              onPress={action.onPress}
              accessibilityRole="button"
              style={({ pressed }) => [styles.sheetRow, pressed && styles.pressed]}
            >
              <Ionicons name={action.icon} size={20} color={action.destructive ? colors.bad : colors.text} />
              <Text style={[styles.sheetLabel, action.destructive && styles.destructive]}>{action.label}</Text>
            </Pressable>
          ))}
          <Pressable onPress={onClose} accessibilityRole="button" style={({ pressed }) => [styles.cancelRow, pressed && styles.pressed]}>
            <Text style={styles.cancelLabel}>Cancel</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** "Are you sure?" dialog with Cancel and a (usually red) confirm button. */
export function ConfirmDialog({
  visible,
  title,
  message,
  confirmLabel,
  destructive,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={busy ? undefined : onCancel}>
      <View style={[styles.backdrop, styles.center]}>
        <View style={styles.dialog} accessibilityRole="alert">
          <Text style={styles.dialogTitle}>{title}</Text>
          <Text style={styles.dialogMessage}>{message}</Text>
          {error && <Text style={styles.dialogError}>{error}</Text>}
          <View style={styles.dialogButtons}>
            <Pressable
              onPress={onCancel}
              disabled={busy}
              accessibilityRole="button"
              style={({ pressed }) => [styles.dialogButton, styles.cancelButton, (pressed || busy) && styles.pressed]}
            >
              <Text style={styles.cancelButtonText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={onConfirm}
              disabled={busy}
              accessibilityRole="button"
              accessibilityLabel={confirmLabel}
              style={({ pressed }) => [
                styles.dialogButton,
                destructive ? styles.destructiveButton : styles.confirmButton,
                pressed && styles.pressed,
              ]}
            >
              {busy ? <ActivityIndicator color={colors.onPrimary} /> : <Text style={styles.confirmText}>{confirmLabel}</Text>}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(20,16,12,0.45)', justifyContent: 'flex-end' },
  center: { justifyContent: 'center', alignItems: 'center', padding: 24 },
  pressed: { opacity: 0.7 },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    paddingTop: 10,
    paddingHorizontal: 12,
    width: '100%',
    maxWidth: 520,
    alignSelf: 'center',
  },
  sheetTitle: { color: colors.muted, fontSize: 13, fontWeight: '600', textAlign: 'center', paddingVertical: 10 },
  sheetRow: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 15, paddingHorizontal: 10, borderRadius: 12 },
  sheetLabel: { color: colors.text, fontSize: 16, fontWeight: '500' },
  destructive: { color: colors.bad },
  cancelRow: { marginTop: 6, paddingVertical: 15, alignItems: 'center', borderRadius: 12, backgroundColor: colors.pill },
  cancelLabel: { color: colors.text, fontSize: 16, fontWeight: '600' },
  dialog: { width: '100%', maxWidth: 360, backgroundColor: colors.surface, borderRadius: 20, padding: 22, gap: 10 },
  dialogTitle: { color: colors.text, fontSize: 18, fontWeight: '700' },
  dialogMessage: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  dialogError: { color: colors.bad, fontSize: 13, lineHeight: 18 },
  dialogButtons: { flexDirection: 'row', gap: 10, marginTop: 8 },
  dialogButton: { flex: 1, height: 46, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  cancelButton: { backgroundColor: colors.pill },
  cancelButtonText: { color: colors.text, fontSize: 15, fontWeight: '600' },
  confirmButton: { backgroundColor: colors.primary },
  destructiveButton: { backgroundColor: colors.bad },
  confirmText: { color: colors.onPrimary, fontSize: 15, fontWeight: '700' },
});
