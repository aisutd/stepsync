import { createContext, useContext, useState, type ReactNode } from 'react';

import type { AnalysisResult, PickedVideo } from '@/api/types';

type Session = {
  reference: PickedVideo | null;
  practice: PickedVideo | null;
  result: AnalysisResult | null;
  currentStep: number;
  completedSteps: number[];
  setCurrentStep: (index: number) => void;
  markStepCompleted: (index: number) => void;
  setReference: (video: PickedVideo | null) => void;
  setPractice: (video: PickedVideo | null) => void;
  setResult: (result: AnalysisResult | null) => void;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [reference, setReference] = useState<PickedVideo | null>(null);
  const [practice, setPractice] = useState<PickedVideo | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);
  const markStepCompleted = (index: number) => setCompletedSteps(prev => prev.includes(index) ? prev : [...prev, index]);
  const replaceReference = (video: PickedVideo | null) => {
    setReference(video);
    setCurrentStep(0);
    setCompletedSteps([]);
    setPractice(null);
    setResult(null);
  };
  const replacePractice = (video: PickedVideo | null) => {
    setPractice(video);
    setResult(null);
  };

  return (
    <SessionContext.Provider
      value={{ reference, practice, result, currentStep, completedSteps, setCurrentStep, markStepCompleted, setReference: replaceReference, setPractice: replacePractice, setResult }}
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
