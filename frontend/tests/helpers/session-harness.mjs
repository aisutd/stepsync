import { readFileSync } from 'node:fs';
import ts from 'typescript';

let serial = 0;

/** Run the real SessionProvider with synchronous React state boundaries. */
export async function createSessionHarness() {
  const slots = [];
  let cursor = 0;
  const key = `__stepSyncSessionHarness${serial++}`;
  globalThis[key] = {
    useState(value) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = value;
      return [slots[index], next => { slots[index] = next; }];
    },
    useRef(value) { const index = cursor++; return slots[index] ??= { current: value }; },
  };
  const compiled = ts.transpileModule(readFileSync(new URL('../../src/state/session.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText.replace(/^import .*;\r?\n/gm, '');
  const prelude = `
    const { useState, useRef } = globalThis['${key}'];
    const useCallback = callback => callback, createContext = () => ({ Provider: 'Provider' }), useContext = () => null;
    const _jsx = (type, props) => ({ type, props });
  `;
  try {
    const { SessionProvider } = await import(`data:text/javascript;base64,${Buffer.from(prelude + compiled).toString('base64')}`);
    return { get session() { cursor = 0; return SessionProvider({ children: null }).props.value; } };
  } finally { delete globalThis[key]; }
}
