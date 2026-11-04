import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { askCoach, getCoaching } from '@/api/client';
import type { CoachingConversation } from '@/api/types';
import { colors } from '@/theme';

const QUESTIONS = ['What should I improve first?', 'What did I do wrong with my arms?',
  'How can I practice the movement at 7 seconds?', 'Which movements matched the reference?'];

/** Key this component by analysis session so mirror retries cannot reuse old context. */
export function CoachingChat({ sessionId, disabled = false }: { sessionId: string; disabled?: boolean }) {
  const [conversation, setConversation] = useState<CoachingConversation | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const pending = useRef<{ question: string; id: string } | null>(null);
  const active = useRef(true);

  useEffect(() => {
    let cancelled = false;
    active.current = true;
    setBusy(true);
    setError(null);
    (async () => {
      try {
        let next = await getCoaching(sessionId);
        if (next.enabled && next.messages.length === 0) next = await askCoach(sessionId);
        if (!cancelled) setConversation(next);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load AI coaching.');
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; active.current = false; };
  }, [sessionId, reload]);

  async function send() {
    const text = question.trim();
    if (!text || busy || disabled || !conversation?.enabled) return;
    if (pending.current?.question !== text) pending.current = { question: text, id: `q_${Date.now()}_${Math.random().toString(36).slice(2)}` };
    const request = pending.current;
    setBusy(true);
    setError(null);
    try {
      const next = await askCoach(sessionId, text, request.id);
      if (active.current) {
        setConversation(next);
        setQuestion('');
        pending.current = null;
      }
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : 'Could not send the coaching question.');
    } finally {
      if (active.current) setBusy(false);
    }
  }

  const unavailable = !conversation?.enabled || conversation.remainingQuestions === 0;
  return <View style={styles.section}>
    <Text style={styles.title}>AI dance coach</Text>
    <Text style={styles.note}>Coaching uses saved comparison evidence. Your scores and detected mistakes remain above.</Text>
    {conversation && <>
      <Text style={styles.scope}>{conversation.coverageStatement}</Text>
      <Text style={styles.note}>{conversation.notice}</Text>
      {conversation.messages.map(message => <View key={message.id} style={styles.message}>
        <Text style={styles.speaker}>{message.role === 'user' ? 'You' : message.source === 'gemini' ? 'Gemini coach' : 'Evidence limitation'}</Text>
        <Text selectable style={styles.text}>{message.text}</Text>
        {message.citations.map(citation => <Text key={citation.id} style={styles.note}>
          Evidence: {citation.label}, {citation.start.toFixed(3)}s to {citation.end.toFixed(3)}s
        </Text>)}
      </View>)}
      {!conversation.enabled && <Text style={styles.note}>AI coaching is not configured. Set GEMINI_API_KEY in the backend environment and restart it. Your numerical results remain available.</Text>}
      {!conversation.enabled && <Pressable accessibilityRole="button" disabled={busy || disabled} onPress={() => setReload(value => value + 1)} style={styles.button}>
        <Text style={styles.text}>Retry coaching</Text>
      </Pressable>}
      {conversation.remainingQuestions === 0 && <Text style={styles.note}>The session's coaching question limit has been reached. Saved answers remain available.</Text>}
    </>}
    {busy && <View accessibilityLiveRegion="polite" style={styles.row}>
      <ActivityIndicator color={colors.primary} /><Text style={styles.text}>Preparing evidence-based coaching...</Text>
    </View>}
    {error && <>
      <Text accessibilityRole="alert" style={styles.error}>{error}</Text>
      <Pressable accessibilityRole="button" disabled={busy || disabled} onPress={() => setReload(value => value + 1)} style={styles.button}>
        <Text style={styles.text}>Retry coaching</Text>
      </Pressable>
    </>}
    {!unavailable && <>
      {QUESTIONS.map(example => <Pressable accessibilityRole="button" key={example} disabled={busy || disabled} onPress={() => setQuestion(example)} style={styles.button}>
        <Text style={styles.text}>{example}</Text>
      </Pressable>)}
      <TextInput accessibilityLabel="Ask the dance coach" placeholder="Ask about a body part or timestamp..." placeholderTextColor={colors.muted}
        value={question} onChangeText={setQuestion} maxLength={1000} multiline editable={!busy && !disabled} style={styles.input} />
      <Pressable accessibilityRole="button" disabled={busy || disabled || !question.trim()} onPress={() => void send()} style={styles.button}>
        <Text style={styles.text}>Send question</Text>
      </Pressable>
    </>}
  </View>;
}

const styles = StyleSheet.create({
  section: { gap: 12, marginTop: 24, paddingTop: 16, borderTopWidth: 1, borderTopColor: colors.border },
  title: { color: colors.text, fontSize: 21, fontWeight: '600' },
  scope: { color: colors.text, fontSize: 14, fontWeight: '600' },
  note: { color: colors.muted, fontSize: 13 },
  text: { color: colors.text, fontSize: 15, lineHeight: 22 },
  speaker: { color: colors.text, fontSize: 14, fontWeight: '600' },
  message: { padding: 14, gap: 8, backgroundColor: colors.surface, borderRadius: 14 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  input: { padding: 12, borderWidth: 1, borderColor: colors.border, borderRadius: 10, color: colors.text, minHeight: 80 },
  button: { padding: 12, borderRadius: 10, backgroundColor: colors.pill },
  error: { color: colors.bad, fontSize: 14 },
});
