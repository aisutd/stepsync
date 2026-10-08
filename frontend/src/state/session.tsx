import { createContext, useContext, useState, type ReactNode } from 'react';

import type { AnalysisResult, PickedVideo } from '@/api/types';

type Session = {
  reference: PickedVideo | null;
  practice: PickedVideo | null;
  result: AnalysisResult | null;
  setReference: (video: PickedVideo | null) => void;
  setPractice: (video: PickedVideo | null) => void;
  setResult: (result: AnalysisResult | null) => void;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [reference, setReference] = useState<PickedVideo | null>(null);
  const [practice, setPractice] = useState<PickedVideo | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  return (
    <SessionContext.Provider
      value={{ reference, practice, result, setReference, setPractice, setResult }}
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
