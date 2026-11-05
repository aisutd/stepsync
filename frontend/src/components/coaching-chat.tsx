import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { askCoach, getCoaching } from '@/api/client';
import type { CoachingConversation } from '@/api/types';
import { colors } from '@/theme';

const QUESTIONS = ['What should I practice first?', 'What can I keep doing?'];

/** Key this component by analysis session so mirror retries cannot reuse old context. */
export function CoachingChat({ sessionId, disabled = false, technicalDetails = false }: { sessionId: string; disabled?: boolean; technicalDetails?: boolean }) {
  const [conversation, setConversation] = useState<CoachingConversation | null>(null);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [showQuestions, setShowQuestions] = useState(false);
  const sending = useRef(false);
  const pending = useRef<{ question: string; id: string } | null>(null);
  const active = useRef(true);

  useEffect(() => {
    if (disabled) return;
    let cancelled = false;
    active.current = true;
    setBusy(true);
    setError(null);
    (async () => {
      try {
        let next = await getCoaching(sessionId);
        if (next.enabled && (next.messages.length === 0 || next.initialReady === false)) next = await askCoach(sessionId);
        if (!cancelled) setConversation(next);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load AI coaching.');
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; active.current = false; };
  }, [sessionId, reload, disabled]);

  async function send() {
    const text = question.trim();
    if (!text || busy || disabled || sending.current || !conversation?.enabled) return;
    sending.current = true;
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
      sending.current = false;
      if (active.current) setBusy(false);
    }
  }

  const unavailable = !conversation?.enabled || conversation.remainingQuestions === 0;
  const summary = conversation?.summary;
  const initial = conversation?.initialMessageId !== undefined
    ? conversation.messages.find(message => message.id === conversation.initialMessageId)
    : conversation?.messages.find(message => message.role === 'assistant');
  return <View style={styles.section}>
    <Text accessibilityRole="header" style={styles.title}>{initial?.source === 'gemini' ? 'Your Gemini practice summary' : 'Your practice summary'}</Text>
    <Text style={styles.note}>Based on movement measurements only. Gemini never receives videos or images.</Text>
    {summary && <>
      <Text style={styles.text}>{summary.impression}</Text>
      {(summary.strengths.length > 0 || summary.improvements.length > 0 || summary.practiceTip) && <>
      {summary.strengths.length > 0 && <View style={styles.message}>
        <Text style={styles.speaker}>What matched</Text>
        {summary.strengths.slice(0, 2).map((text, index) => <Text key={index} style={styles.text}>{text}</Text>)}
      </View>}
      {summary.improvements.length > 0 && <View style={styles.message}>
        <Text style={styles.speaker}>What to work on</Text>
        {summary.improvements.slice(0, 2).map((text, index) => <Text key={index} style={styles.text}>{text}</Text>)}
      </View>}
      {summary.practiceTip && <View style={styles.tip}>
        <Text style={styles.speaker}>Try this next</Text><Text style={styles.text}>{summary.practiceTip}</Text>
      </View>}
      </>}
      {summary.note && <Text style={styles.note}>{summary.note}</Text>}
    </>}
    {busy && <View accessibilityLiveRegion="polite" style={styles.row}>
      <ActivityIndicator color={colors.primary} /><Text style={styles.text}>Preparing your coaching...</Text>
    </View>}
    {!busy && !summary && !error && <Text style={styles.note}>
      {conversation?.enabled ? 'A concise summary is not available for this saved session. You can ask a follow-up below.' : 'AI coaching is not configured. Your analysis is saved; technical details remain available.'}
    </Text>}
    {error && <Text accessibilityRole="alert" style={styles.error}>Coaching is unavailable right now. Your analysis is saved. Please try again.</Text>}
    {(error || !conversation?.enabled) && !busy && <Pressable accessibilityRole="button" disabled={disabled} onPress={() => setReload(value => value + 1)} style={styles.button}>
      <Text style={styles.text}>Retry coaching</Text>
    </Pressable>}
    {technicalDetails && <View style={styles.message}>
      <Text style={styles.speaker}>Coaching evidence</Text>
      {error && <Text selectable style={styles.note}>{error}</Text>}
      {conversation && <>
        <Text style={styles.note}>{conversation.coverageStatement}</Text>
        <Text style={styles.note}>{conversation.notice}</Text>
        {conversation.messages.filter(message => message.role === 'assistant').map(message => <View key={message.id} style={styles.rowDetails}>
          <Text selectable style={styles.note}>{message.text}</Text>
          {message.citations.map(citation => <Text selectable key={citation.id} style={styles.note}>{citation.fact}</Text>)}
        </View>)}
      </>}
    </View>}
    {conversation && (!unavailable || conversation.messages.length > 1) && <Pressable accessibilityRole="button" accessibilityState={{ expanded: showQuestions }} disabled={busy || disabled} onPress={() => setShowQuestions(!showQuestions)} style={styles.button}>
      <Text style={styles.text}>{showQuestions ? 'Hide follow-up questions' : 'Ask a follow-up'}</Text>
    </Pressable>}
    {showQuestions && <>
      {conversation?.messages.filter(message => message.id !== initial?.id).map(message => <View key={message.id} style={styles.message}>
        <Text style={styles.speaker}>{message.role === 'user' ? 'You' : 'Coach'}</Text>
        <Text selectable style={styles.text}>{message.text}</Text>
      </View>)}
      {conversation?.remainingQuestions === 0 && <Text style={styles.note}>This session's question limit has been reached. Your saved answers remain available.</Text>}
      {!unavailable && <>
        {QUESTIONS.map(example => <Pressable accessibilityRole="button" key={example} disabled={busy || disabled} onPress={() => setQuestion(example)} style={styles.button}>
          <Text style={styles.text}>{example}</Text>
        </Pressable>)}
        <TextInput accessibilityLabel="Ask the dance coach" placeholder="What would you like to practice?" placeholderTextColor={colors.muted}
          value={question} onChangeText={setQuestion} maxLength={1000} multiline editable={!busy && !disabled} style={styles.input} />
        <Pressable accessibilityRole="button" disabled={busy || disabled || !question.trim()} onPress={() => void send()} style={styles.button}>
          <Text style={styles.text}>Send question</Text>
        </Pressable>
      </>}
    </>}
  </View>;
}

const styles = StyleSheet.create({
  section: { gap: 14 },
  title: { color: colors.text, fontSize: 21, fontWeight: '600' },
  scope: { color: colors.text, fontSize: 14, fontWeight: '600' },
  note: { color: colors.muted, fontSize: 13 },
  text: { color: colors.text, fontSize: 15, lineHeight: 22 },
  speaker: { color: colors.text, fontSize: 14, fontWeight: '600' },
  message: { padding: 14, gap: 8, backgroundColor: colors.surface, borderRadius: 14 },
  tip: { padding: 16, gap: 8, backgroundColor: colors.pill, borderRadius: 14 },
  rowDetails: { gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  input: { padding: 12, borderWidth: 1, borderColor: colors.border, borderRadius: 10, color: colors.text, minHeight: 80 },
  button: { padding: 12, borderRadius: 10, backgroundColor: colors.pill },
  error: { color: colors.bad, fontSize: 14 },
});
