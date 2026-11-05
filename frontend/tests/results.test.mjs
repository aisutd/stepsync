import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { createSessionHarness } from './helpers/session-harness.mjs';
import { analysisPresentation } from '../src/api/analysis-presentation.ts';

// Execute the screen's render/event logic with native widgets and hooks replaced.
// This checks state transitions without a browser or an additional renderer dependency.
const compiled = ts.transpileModule(readFileSync(new URL('../src/app/results.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText.replace(/^import .*;\r?\n/gm, '');
const prelude = `
const boundary = globalThis.__stepSyncResultsTest;
const _jsx = (type, props) => ({ type, props });
const _jsxs = _jsx;
const { useRef, useState, useSession, retryAnalysis, analysisPresentation } = boundary;
const useRouter = () => ({ replace() {} });
const useCallback = callback => callback, useFocusEffect = callback => boundary.useFocusEffect(callback);
const useVideoPlayer = () => ({ currentTime: 0, play() {} });
const StyleSheet = { create: (value) => value };
const Linking = { openURL() {} }, analysisDiagnosticsUrl = (id) => '/analyses/' + id + '/diagnostics';
const colors = {}, scoreColor = () => '';
const Redirect = 'Redirect', VideoView = 'VideoView', ActivityIndicator = 'ActivityIndicator';
const ScrollView = 'ScrollView', FlatList = 'FlatList', Pressable = 'Pressable', Text = 'Text', View = 'View', CoachingChat = 'CoachingChat';
`;

function nodes(element) {
  if (!element || typeof element !== 'object') return [];
  const children = [element.props?.children, element.props?.ListHeaderComponent, element.props?.ListFooterComponent].flat(Infinity);
  return [element, ...children.flatMap(nodes)];
}

test('results automatically coaches ambiguous mapping; side overrides stay advanced and preserve retry behavior', async () => {
  const original = { sessionId: 'a'.repeat(32), steps: [], assessment: { totalFrames: 780, assessedFrames: 36, unassessedFrames: 744 },
    alignment: { mirrorSelection: { requestedMode: 'auto', ambiguous: true } } };
  const sessionHarness = await createSessionHarness();
  sessionHarness.session.setPractice({ uri: 'local-video' });
  sessionHarness.session.setResult(original);
  let cleanup;
  const slots = [];
  let cursor = 0;
  let calls = 0;
  let finish, fail;
  globalThis.__stepSyncResultsTest = {
    analysisPresentation,
    useRef(value) { const index = cursor++; return slots[index] ??= { current: value }; },
    useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value;
      return [slots[index], (next) => { slots[index] = next; }]; },
    useSession: () => sessionHarness.session,
    useFocusEffect: callback => { if (!cleanup) cleanup = callback(); },
    retryAnalysis: () => { calls++; return new Promise((resolve, reject) => { finish = resolve; fail = reject; }); },
  };
  try {
    const { default: Screen } = await import(`data:text/javascript;base64,${Buffer.from(prelude + compiled).toString('base64')}`);
    const render = () => { cursor = 0; return Screen(); };
    let tree = render();
    assert.equal(nodes(tree).some(node => node.type === 'CoachingChat'), true);
    assert.equal(nodes(tree).filter(node => node.type === 'Pressable' && ['Same sides', 'Mirror movements'].includes(node.props.children?.props?.children)).length, 0);
    const open = nodes(tree).find(node => node.type === 'Pressable' && node.props.children?.props?.children === 'View technical details');
    open.props.onPress();
    tree = render();
    assert.equal(nodes(tree).some(node => node.type === 'VideoView'), true);
    let buttons = nodes(tree).filter((node) => node.type === 'Pressable' && ['Same sides', 'Mirror movements'].includes(node.props.children?.props?.children));
    assert.equal(buttons.length, 2);
    buttons[0].props.onPress();
    buttons[1].props.onPress();
    assert.equal(calls, 1);
    assert.equal(sessionHarness.session.result, original);
    tree = render();
    assert.ok(nodes(tree).filter((node) => node.type === 'Pressable' && node.props.accessibilityRole === 'button').every((node) => node.props.disabled));
    fail(new Error('Saved pose data unavailable'));
    await new Promise(setImmediate);
    tree = render();
    assert.equal(sessionHarness.session.result, original);
    assert.ok(nodes(tree).some((node) => node.props?.accessibilityRole === 'alert'));
    assert.equal(nodes(tree).some(node => node.type === 'CoachingChat'), true);
    buttons = nodes(tree).filter((node) => node.type === 'Pressable' && node.props.children?.props?.children === 'Same sides');
    buttons[0].props.onPress();
    const confirmed = { ...original, sessionId: 'b'.repeat(32), alignment: { mirrorSelection: { requestedMode: 'same', ambiguous: false } } };
    finish(confirmed);
    await new Promise(setImmediate);
    tree = render();
    assert.equal(sessionHarness.session.result, confirmed);
    const coach = nodes(tree).find(node => node.type === 'CoachingChat');
    assert.equal(coach.props.sessionId, confirmed.sessionId);
    const close = nodes(tree).find(node => node.type === 'Pressable' && node.props.children?.props?.children === 'Hide technical details');
    close.props.onPress();
    tree = render();
    assert.equal(nodes(tree).find(node => node.type === 'CoachingChat').props.technicalDetails, false);
    assert.equal(nodes(tree).some(node => node.type === 'VideoView'), false);
    const toggle = nodes(tree).find(node => node.type === 'Pressable' && node.props.children?.props?.children === 'View technical details');
    assert.equal(toggle.props.accessibilityState.expanded, false);
    toggle.props.onPress();
    tree = render();
    assert.equal(nodes(tree).some(node => node.type === 'VideoView'), true);
    assert.equal(nodes(tree).find(node => node.type === 'CoachingChat').props.technicalDetails, true);
    assert.ok(nodes(tree).some(node => node.type === 'Text' && node.props.children === '36 / 780 frames assessed (4.62%)'));
    const hide = nodes(tree).find(node => node.type === 'Pressable' && node.props.children?.props?.children === 'Hide technical details');
    hide.props.onPress();
    assert.equal(nodes(render()).some(node => node.type === 'VideoView'), false);
  } finally {
    delete globalThis.__stepSyncResultsTest;
  }
});

test('late retry success, error and progress cannot leak across navigation or a newer analysis', async () => {
  for (const scenario of ['blur', 'new-result', 'new-analysis', 'new-video', 'late-error']) {
    const sessionHarness = await createSessionHarness();
    const original = { sessionId: 'a'.repeat(32), steps: [] };
    const newer = { sessionId: 'c'.repeat(32), steps: [] };
    sessionHarness.session.setPractice({ uri: 'practice-a' });
    sessionHarness.session.setResult(original);
    const slots = [];
    let cursor = 0, cleanup, finish, fail, progress;
    const boundary = {
      analysisPresentation,
      useRef(value) { const index = cursor++; return slots[index] ??= { current: value }; },
      useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value;
        return [slots[index], next => { slots[index] = next; }]; },
      useFocusEffect(callback) { if (!cleanup) cleanup = callback(); },
      useSession: () => sessionHarness.session,
      retryAnalysis: (_id, _mode, _reference, _practice, onProgress) => {
        progress = onProgress;
        return new Promise((resolve, reject) => { finish = resolve; fail = reject; });
      },
    };
    globalThis.__stepSyncResultsTest = boundary;
    try {
      const { default: Screen } = await import(`data:text/javascript;base64,${Buffer.from(prelude + compiled + `\n// race: ${scenario}`).toString('base64')}`);
      const render = () => { cursor = 0; return Screen(); };
      let tree = render();
      nodes(tree).find(node => node.props?.children?.props?.children === 'View technical details').props.onPress();
      tree = render();
      nodes(tree).find(node => node.props?.children?.props?.children === 'Same sides').props.onPress();
      if (scenario === 'blur') cleanup();
      else if (scenario === 'new-video') sessionHarness.session.setPractice({ uri: 'practice-b' });
      else if (scenario === 'new-analysis') sessionHarness.session.beginResultRequest();
      else sessionHarness.session.setResult(newer);
      const before = [...slots];
      progress(.5);
      assert.deepEqual(slots, before); // No stale progress updates, even without a rerender.
      if (scenario === 'late-error') fail(new Error('Old request failed'));
      else finish({ sessionId: 'b'.repeat(32), steps: [] });
      await new Promise(setImmediate);
      assert.equal(sessionHarness.session.result, scenario === 'new-video' ? null
        : ['new-result', 'late-error'].includes(scenario) ? newer : original);
      if (scenario === 'late-error') {
        assert.equal(nodes(render()).some(node => node.props?.accessibilityRole === 'alert'), false);
      }
    } finally { delete globalThis.__stepSyncResultsTest; }
  }
});

test('returning to results can start a new override without an old completion clearing its loading state', async () => {
  const sessionHarness = await createSessionHarness();
  const original = { sessionId: 'a'.repeat(32), steps: [] };
  sessionHarness.session.setPractice({ uri: 'practice-a' });
  sessionHarness.session.setResult(original);
  const slots = [], requests = [];
  let cursor = 0, cleanup;
  globalThis.__stepSyncResultsTest = {
    analysisPresentation,
    useRef(value) { const index = cursor++; return slots[index] ??= { current: value }; },
    useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value;
      return [slots[index], next => { slots[index] = next; }]; },
    useSession: () => sessionHarness.session,
    useFocusEffect(callback) { if (!cleanup) cleanup = callback(); },
    retryAnalysis: (_id, mode) => new Promise(resolve => requests.push({ mode, resolve })),
  };
  try {
    const { default: Screen } = await import(`data:text/javascript;base64,${Buffer.from(prelude + compiled + '\n// refocus').toString('base64')}`);
    const render = () => { cursor = 0; return Screen(); };
    const button = (tree, label) => nodes(tree).find(node => node.props?.children?.props?.children === label);
    button(render(), 'View technical details').props.onPress();
    button(render(), 'Same sides').props.onPress();
    cleanup();
    cleanup = null;
    // useFocusEffect resets the spinner on focus; rerender to observe its state.
    render();
    button(render(), 'Mirror movements').props.onPress();
    assert.deepEqual(requests.map(request => request.mode), ['same', 'mirrored']);
    requests[0].resolve({ sessionId: 'b'.repeat(32), steps: [] });
    await new Promise(setImmediate);
    assert.equal(sessionHarness.session.result, original);
    assert.equal(button(render(), 'Mirror movements').props.disabled, true);
    const replacement = { sessionId: 'c'.repeat(32), steps: [] };
    requests[1].resolve(replacement);
    await new Promise(setImmediate);
    assert.equal(sessionHarness.session.result, replacement);
    assert.equal(button(render(), 'Mirror movements').props.disabled, false);
  } finally { delete globalThis.__stepSyncResultsTest; }
});
