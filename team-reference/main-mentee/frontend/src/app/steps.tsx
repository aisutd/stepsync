import { Asset } from 'expo-asset';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Image, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop, SvgUri } from 'react-native-svg';

import { PrimaryButton } from '@/components/primary-button';
import { grapevineCounts as counts, lessonStepIndex } from '@/data/lesson';
import { colors, lessonColors as palette, radius } from '@/theme';

const icons = {
  signal: require('../../assets/steps/signal.svg'),
  wifi: require('../../assets/steps/wifi.svg'),
  battery: require('../../assets/steps/battery.svg'),
  back: require('../../assets/steps/back.svg'),
  volume: require('../../assets/steps/volume.svg'),
  travel: require('../../assets/steps/travel-left.svg'),
  sparkles: require('../../assets/steps/sparkles.svg'),
  previous: require('../../assets/steps/previous.svg'),
  next: require('../../assets/steps/next.svg'),
};

// Keep the exported Figma icons at their original dimensions on both platforms.
function DesignIcon({ name, size = 16, width = size }: { name: keyof typeof icons; size?: number; width?: number }) {
  const source = icons[name];
  return Platform.OS === 'web'
    ? <Image source={source} style={{ width, height: size }} resizeMode="contain" />
    : <SvgUri uri={Asset.fromModule(source).uri} width={width} height={size} />;
}

export default function StepsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ step?: string }>();
  const [step, setStep] = useState(() => lessonStepIndex(params.step));
  const leave = () => router.canGoBack() ? router.back() : router.replace('/');

  return (
    <ScrollView style={styles.fill} contentContainerStyle={styles.canvas} showsVerticalScrollIndicator={false}>
      <View testID="grapevine-lesson" style={[styles.screen, { paddingTop: Platform.OS === 'web' ? 0 : insets.top, paddingBottom: Math.max(18, insets.bottom) }]}>
        {Platform.OS === 'web' && (
          <View style={styles.status} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <Text style={styles.time}>9:41</Text>
            <View style={styles.statusIcons}>
              <DesignIcon name="signal" size={15} />
              <DesignIcon name="wifi" size={15} />
              <DesignIcon name="battery" size={15} width={21} />
            </View>
          </View>
        )}

        <View style={styles.header}>
          <Pressable accessibilityRole="button" accessibilityLabel="Back to home" onPress={leave} style={({ pressed }) => [styles.back, pressed && styles.pressed]}>
            <DesignIcon name="back" size={17} />
          </Pressable>
          <View style={styles.lesson}>
            <Text style={styles.lessonLabel}>LESSON 2 OF 6</Text>
            <View style={styles.track}><View style={styles.progress} /></View>
          </View>
          <View style={styles.balance} />
        </View>

        <View style={styles.content}>
          <View style={styles.introduction}>
            <Text style={styles.level}>SIDE-TRAVELING STEP · BEGINNER</Text>
            <Text style={styles.title} accessibilityRole="header">The Grapevine</Text>
            <Text style={styles.cue}>Step, cross behind, step, tap.</Text>
          </View>

          <View style={styles.demo}>
            <Image testID="grapevine-demo-image" source={require('../../assets/steps/grapevine.png')} accessibilityLabel="Grapevine demonstration: dancer crossing one foot behind the other in a studio" style={styles.demoImage} resizeMode="cover" />
            <Svg width="100%" height="100%" style={StyleSheet.absoluteFill} pointerEvents="none">
              <Defs><LinearGradient id="demoShade" x1="0" y1="0" x2="0" y2="1"><Stop offset="0.35" stopColor="#17120B" stopOpacity={0} /><Stop offset="1" stopColor="#17120B" stopOpacity={0.44} /></LinearGradient></Defs>
              <Rect width="100%" height="100%" fill="url(#demoShade)" />
            </Svg>
            <View style={styles.demoBadge}><View style={styles.dot} /><Text style={styles.demoLabel}>DEMO · 0:08</Text></View>
            {/* Figma provides a still image, so the audio indicator is decorative. */}
            <View style={styles.audio}><DesignIcon name="volume" size={15} /></View>
            <View style={styles.travel}><DesignIcon name="travel" /><Text style={styles.travelText}>Travel to your left</Text></View>
          </View>

          <View style={styles.footwork}>
            <View style={styles.sectionHeading}><Text style={styles.sectionTitle}>Four-count footwork</Text><Text style={styles.tempo}>92 BPM</Text></View>
            <View style={styles.counts} accessibilityLiveRegion="polite">
              {counts.map((count, index) => {
                const active = index === step;
                const upcoming = index > step;
                return (
                  <View key={index} accessibilityLabel={`Count ${index + 1}: ${count.action.replace('\n', ' ')}, ${count.foot}${active ? ', current step' : ''}`} style={[styles.count, active && styles.activeCount]}>
                    <View style={[styles.marker, upcoming && styles.upcomingMarker, active && styles.activeMarker]}><Text style={styles.number}>{index + 1}</Text></View>
                    <Text style={[styles.action, upcoming && styles.upcomingText]}>{count.action}</Text>
                    <Text style={[styles.foot, upcoming && styles.upcomingText]}>{count.foot}</Text>
                  </View>
                );
              })}
            </View>
          </View>

          <View style={styles.tip}>
            <View style={styles.tipIcon}><DesignIcon name="sparkles" /></View>
            <View style={styles.tipCopy}><Text style={styles.tipLabel}>COACHING TIP</Text><Text style={styles.tipText}>Keep your hips forward as the right foot crosses behind.</Text></View>
          </View>

          <View style={styles.navigation}>
            <Pressable accessibilityRole="button" onPress={() => step === 0 ? leave() : setStep(step - 1)} style={({ pressed }) => [styles.previous, pressed && styles.pressed]}>
              <DesignIcon name="previous" /><Text style={styles.previousLabel}>Previous</Text>
            </Pressable>
            <PrimaryButton
              label="Practice Now"
              onPress={() => router.push({ pathname: '/step-recording', params: { step: String(step + 1) } })}
              style={styles.next}
              labelStyle={styles.nextLabel}
              trailingIcon={<View style={styles.nextIcon}><DesignIcon name="next" /></View>}
            />
          </View>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: palette.background },
  canvas: { flexGrow: 1, alignItems: 'center' },
  screen: { width: '100%', maxWidth: 390, minHeight: Platform.OS === 'web' ? 844 : undefined, backgroundColor: palette.background },
  status: { height: 42, paddingHorizontal: 24, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  time: { fontSize: 12, color: palette.text },
  statusIcons: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  header: { height: 54, paddingHorizontal: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  back: { width: 36, height: 36, borderRadius: radius.pill, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface, alignItems: 'center', justifyContent: 'center' },
  balance: { width: 36, height: 36 },
  lesson: { width: 136, alignItems: 'center', gap: 6 },
  lessonLabel: { color: palette.secondary, fontSize: 10, fontWeight: '700', letterSpacing: 1.1, lineHeight: 12 },
  track: { height: 4, width: '100%', borderRadius: radius.pill, backgroundColor: palette.track, overflow: 'hidden' },
  progress: { width: 45, height: 4, borderRadius: radius.pill, backgroundColor: palette.accent },
  content: { paddingHorizontal: 20, paddingTop: 12, gap: 16 },
  introduction: { gap: 5 },
  level: { color: palette.accent, fontSize: 10, lineHeight: 12, fontWeight: '700', letterSpacing: 1.2 },
  title: { color: palette.text, fontSize: 32, lineHeight: 34, letterSpacing: -0.8 },
  cue: { color: palette.muted, fontSize: 13, lineHeight: 16 },
  demo: { width: '100%', height: 332, borderRadius: 24, overflow: 'hidden', boxShadow: '0px 8px 22px rgba(58,45,33,0.08)' },
  demoImage: { ...StyleSheet.absoluteFill, width: '100%', height: '100%' },
  demoBadge: { position: 'absolute', top: 12, left: 12, paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: 'rgba(255,252,247,0.91)', flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 6, height: 6, borderRadius: radius.pill, backgroundColor: palette.accent },
  demoLabel: { color: palette.text, fontSize: 10, fontWeight: '700', letterSpacing: 0.7, lineHeight: 12 },
  audio: { position: 'absolute', top: 12, right: 12, width: 34, height: 34, borderRadius: radius.pill, backgroundColor: 'rgba(255,252,247,0.91)', alignItems: 'center', justifyContent: 'center' },
  travel: { position: 'absolute', bottom: 16, left: 16, paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: 'rgba(27,25,22,0.8)', flexDirection: 'row', alignItems: 'center', gap: 7 },
  travelText: { color: colors.onPrimary, fontSize: 12, lineHeight: 15 },
  footwork: { gap: 8 },
  sectionHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sectionTitle: { color: palette.text, fontSize: 13, lineHeight: 16, fontWeight: '700' },
  tempo: { color: palette.muted, fontSize: 10, fontWeight: '600' },
  counts: { flexDirection: 'row', gap: 7 },
  count: { flex: 1, minWidth: 0, height: 76, paddingTop: 7, gap: 4, alignItems: 'center', borderRadius: 16, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface },
  activeCount: { borderColor: palette.accent, backgroundColor: palette.selected },
  marker: { width: 22, height: 22, borderRadius: radius.pill, backgroundColor: palette.text, alignItems: 'center', justifyContent: 'center' },
  activeMarker: { backgroundColor: palette.accent },
  upcomingMarker: { backgroundColor: palette.upcoming },
  number: { color: colors.onPrimary, fontSize: 10, fontWeight: '700', lineHeight: 12 },
  action: { color: palette.text, fontSize: 10, lineHeight: 11, textAlign: 'center', fontWeight: '700', letterSpacing: 0.3 },
  foot: { color: palette.muted, fontSize: 9, lineHeight: 11, fontWeight: '500' },
  upcomingText: { color: palette.upcoming },
  tip: { minHeight: 71, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface, borderRadius: 16, paddingHorizontal: 13, paddingVertical: 11, flexDirection: 'row', alignItems: 'center', gap: 12 },
  tipIcon: { width: 34, height: 34, borderRadius: radius.pill, backgroundColor: palette.selected, alignItems: 'center', justifyContent: 'center' },
  tipCopy: { flex: 1, gap: 3 },
  tipLabel: { color: palette.accent, fontSize: 10, letterSpacing: 0.8, lineHeight: 12 },
  tipText: { color: palette.secondary, fontSize: 12, fontWeight: '500', lineHeight: 15.6 },
  navigation: { flexDirection: 'row', gap: 12 },
  previous: { flex: 1, height: 52, borderRadius: radius.pill, borderWidth: 1, borderColor: palette.border, backgroundColor: palette.surface, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  previousLabel: { color: palette.text, fontSize: 13 },
  next: { flex: 1, height: 52, borderRadius: radius.pill, backgroundColor: palette.text, paddingHorizontal: 10 },
  nextLabel: { fontSize: 13, fontWeight: '400' },
  nextIcon: { marginLeft: 8 },
  pressed: { opacity: 0.75 },
});
