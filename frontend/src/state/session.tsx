import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

import type { AnalysisResult, PickedVideo } from '@/api/types';

type Session = {
  reference: PickedVideo | null;
  practice: PickedVideo | null;
  result: AnalysisResult | null;
  setReference: (video: PickedVideo | null) => void;
  setPractice: (video: PickedVideo | null) => void;
  setResult: (result: AnalysisResult | null) => void;
  beginResultRequest: () => { isCurrent: () => boolean; commit: (result: AnalysisResult) => boolean };
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [reference, updateReference] = useState<PickedVideo | null>(null);
  const [practice, updatePractice] = useState<PickedVideo | null>(null);
  const [result, updateResult] = useState<AnalysisResult | null>(null);
  const generation = useRef(0);
  // Invalidate synchronously, including before React renders the new selection.
  const setReference = useCallback((video: PickedVideo | null) => {
    generation.current++;
    updateReference(video);
    updateResult(null);
  }, []);
  const setPractice = useCallback((video: PickedVideo | null) => {
    generation.current++;
    updatePractice(video);
    updateResult(null);
  }, []);
  const setResult = useCallback((next: AnalysisResult | null) => {
    generation.current++;
    updateResult(next);
  }, []);
  const beginResultRequest = useCallback(() => {
    const requestedGeneration = ++generation.current;
    const isCurrent = () => generation.current === requestedGeneration;
    return { isCurrent, commit: (next: AnalysisResult) => {
      if (!isCurrent()) return false;
      setResult(next);
      return true;
    } };
  }, [setResult]);

  return (
    <SessionContext.Provider
      value={{ reference, practice, result, setReference, setPractice, setResult, beginResultRequest }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error('useSession must be used inside SessionProvider');
  return session;
}
