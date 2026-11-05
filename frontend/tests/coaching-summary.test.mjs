import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const compiled = ts.transpileModule(readFileSync(new URL('../src/components/coaching-chat.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText.replace(/^import .*;\r?\n/gm, '');
const prelude = `
const { useState } = globalThis.__stepSyncCoachingTest;
const useRef = (value) => ({ current: value }), useEffect = () => {};
const _jsx = (type, props) => ({ type, props }), _jsxs = _jsx;
const _Fragment = 'Fragment';
const StyleSheet = { create: (value) => value }, colors = {};
const ActivityIndicator = 'ActivityIndicator', Pressable = 'Pressable', Text = 'Text', TextInput = 'TextInput', View = 'View';
const askCoach = () => { throw new Error('Unexpected provider request during render'); }, getCoaching = askCoach;
`;

function nodes(element) {
  if (!element || typeof element !== 'object') return [];
  return [element, ...[element.props?.children].flat(Infinity).flatMap(nodes)];
}
const textOf = (tree) => nodes(tree).filter(node => node.type === 'Text')
  .map(node => [node.props.children].flat(Infinity).filter(value => typeof value === 'string').join('')).join('\n');

test('coaching leads with bounded summary; raw findings and follow-up history are opt-in', async () => {
  const conversation = {
    enabled: true, remainingQuestions: 19, coverageStatement: '36 of 780 frames were assessed.', notice: 'Saved evidence only.',
    summary: { impression: 'Only supported sections were compared.', strengths: ['Supported elbow checkpoint.'],
      improvements: ['Focus on matching the knee position.'], practiceTip: 'Repeat the supported section slowly.', note: 'Other sections remain unassessed.' },
    messages: [
      { id: 'initial', role: 'assistant', source: 'gemini', text: 'Your knee measured 130 degrees.',
        citations: [{ id: 'knee', fact: 'Reference: 160 degrees at 1s.' }] },
      { id: 'q1', role: 'user', source: 'user', text: 'My last question', citations: [] },
      { id: 'a1', role: 'assistant', source: 'gemini', text: 'The saved follow-up answer', citations: [] },
    ],
  };
  const slots = [conversation, '', false, null, 0, false];
  let cursor = 0;
  globalThis.__stepSyncCoachingTest = {
    useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value;
      return [slots[index], (next) => { slots[index] = next; }]; },
  };
  try {
    const { CoachingChat } = await import(`data:text/javascript;base64,${Buffer.from(prelude + compiled).toString('base64')}`);
    const render = (technicalDetails = false) => { cursor = 0; return CoachingChat({ sessionId: 'a'.repeat(32), technicalDetails }); };
    let tree = render();
    let text = textOf(tree);
    for (const phrase of ['Your Gemini practice summary', 'What matched', 'What to work on', 'Try this next', conversation.summary.practiceTip]) assert.ok(text.includes(phrase));
    assert.equal(text.split(conversation.summary.note).length - 1, 1);
    assert.ok(text.indexOf(conversation.summary.note) > text.indexOf(conversation.summary.practiceTip));
    for (const phrase of ['130 degrees', '160 degrees', '36 of 780', 'My last question', '7 seconds']) assert.ok(!text.includes(phrase));
    assert.equal(nodes(tree).some(node => node.type === 'TextInput'), false);
    text = textOf(render(true));
    for (const phrase of ['130 degrees', '160 degrees', '36 of 780']) assert.ok(text.includes(phrase));
    const ask = nodes(tree).find(node => node.type === 'Pressable' && node.props.children?.props?.children === 'Ask a follow-up');
    ask.props.onPress();
    tree = render();
    assert.ok(textOf(tree).includes('My last question'));
    assert.equal(nodes(tree).some(node => node.type === 'TextInput'), true);
    slots[5] = false;
    slots[0] = { ...conversation, enabled: false, remainingQuestions: 0 };
    assert.ok(textOf(render()).includes('Ask a follow-up')); // History remains accessible without a key/quota.
    slots[0] = { ...conversation, summary: { ...conversation.summary, strengths: [], improvements: [], practiceTip: null } };
    text = textOf(render());
    assert.ok(!text.includes('What matched'));
    assert.ok(!text.includes('Try this next'));
    assert.ok(text.includes(conversation.summary.impression));
    assert.ok(!text.includes('Supported elbow checkpoint.'));
    // A follow-up may precede the actual initial answer in API history.
    slots[0] = { ...conversation, initialMessageId: 'initial', messages: [
      { id: 'earlier', role: 'assistant', source: 'evidence', text: 'Earlier follow-up', citations: [] },
      ...conversation.messages,
    ] };
    slots[5] = true;
    text = textOf(render());
    assert.ok(text.includes('Your Gemini practice summary'));
    assert.ok(text.includes('Earlier follow-up'));
    assert.ok(!text.includes('130 degrees')); // Initial text stays in technical details, not follow-up history.
    slots[5] = false;
    slots[0] = { ...conversation, summary: { impression: 'I cannot support that conclusion from these measurements.',
      strengths: [], improvements: [], practiceTip: null, note: null } };
    text = textOf(render());
    assert.ok(text.includes(slots[0].summary.impression));
    assert.ok(!text.includes('What matched') && !text.includes('Try this next'));
    slots[0] = null;
    slots[3] = 'PRIVATE-PROVIDER-ERROR';
    assert.ok(!textOf(render()).includes('PRIVATE-PROVIDER-ERROR'));
    assert.ok(textOf(render(true)).includes('PRIVATE-PROVIDER-ERROR'));
  } finally { delete globalThis.__stepSyncCoachingTest; }
});

test('coaching loads automatically for new sessions and refreshes an obsolete initial response', async () => {
  for (const stale of [false, true]) {
    let cursor = 0;
    const slots = [];
    let effect;
    const calls = [];
    const summary = { impression: 'Some bilateral ranges could be compared.', strengths: ['A supported bilateral checkpoint.'], improvements: [],
      practiceTip: 'Repeat this supported range slowly.', note: 'Individual sides remain unknown.' };
    globalThis.__stepSyncCoachingTest = {
      useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value;
        return [slots[index], next => { slots[index] = next; }]; },
      useEffect(callback) { effect = callback; },
      getCoaching: async (...args) => { calls.push(['get', ...args]); return {
        enabled: true, initialReady: false, messages: stale ? [{ id: 'old', role: 'assistant', source: 'evidence', text: 'Old cached response', citations: [] }] : [],
        summary: null, remainingQuestions: 20,
      }; },
      askCoach: async (...args) => { calls.push(['post', ...args]); return {
        enabled: true, initialReady: true, summary, remainingQuestions: 20,
        messages: [{ id: 'safe', role: 'assistant', source: 'gemini', text: 'Safe summary', citations: [] }],
      }; },
    };
    const autoPrelude = prelude
      .replace('useEffect = () => {}', 'useEffect = (...args) => globalThis.__stepSyncCoachingTest.useEffect(...args)')
      .replace("const askCoach = () => { throw new Error('Unexpected provider request during render'); }, getCoaching = askCoach;",
        'const { askCoach, getCoaching } = globalThis.__stepSyncCoachingTest;');
    try {
      const { CoachingChat } = await import(`data:text/javascript;base64,${Buffer.from(autoPrelude + compiled + `\n// stale: ${stale}`).toString('base64')}`);
      CoachingChat({ sessionId: 'a'.repeat(32) });
      effect();
      await new Promise(setImmediate);
      assert.deepEqual(calls, [['get', 'a'.repeat(32)], ['post', 'a'.repeat(32)]]);
      cursor = 0;
      const text = textOf(CoachingChat({ sessionId: 'a'.repeat(32) }));
      assert.ok(text.includes(summary.impression));
      assert.ok(text.includes(summary.practiceTip));
      assert.ok(!text.includes('confirm movement sides'));
    } finally { delete globalThis.__stepSyncCoachingTest; }
  }
});
