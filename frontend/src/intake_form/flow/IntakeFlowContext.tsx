import type React from "react";
import { createContext, useContext, useMemo, useState } from "react";

export type SubmitSuccess = {
  clientId: string;
  intakeSubmissionId?: string;
} | null;

type IntakeFlowContextValue = {
  clientId: string | null;
  setClientId: (value: string | null) => void;
  draftId: string | null;
  setDraftId: (value: string | null) => void;

  consultDone: boolean;
  setConsultDone: (value: boolean) => void;
  consultFinal: any | null;
  setConsultFinal: (value: any | null) => void;

  targetMarketDone: boolean;
  setTargetMarketDone: (value: boolean) => void;
  targetMarketSummary: string | null;
  setTargetMarketSummary: (value: string | null) => void;

  peopleDone: boolean;
  setPeopleDone: (value: boolean) => void;
  keyPeopleSummary: string | null;
  setKeyPeopleSummary: (value: string | null) => void;

  submitLoading: boolean;
  setSubmitLoading: (value: boolean) => void;
  submitError: string | null;
  setSubmitError: (value: string | null) => void;
  submitSuccess: SubmitSuccess;
  setSubmitSuccess: (value: SubmitSuccess) => void;

  resetCounter: number;
  bumpResetCounter: () => void;
};

const IntakeFlowContext = createContext<IntakeFlowContextValue | null>(null);

export function IntakeFlowProvider({ children }: { children: React.ReactNode }) {
  const [clientId, setClientId] = useState<string | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [consultDone, setConsultDone] = useState(false);
  const [consultFinal, setConsultFinal] = useState<any | null>(null);
  const [targetMarketDone, setTargetMarketDone] = useState(false);
  const [targetMarketSummary, setTargetMarketSummary] = useState<string | null>(
    null
  );
  const [peopleDone, setPeopleDone] = useState(false);
  const [keyPeopleSummary, setKeyPeopleSummary] = useState<string | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<SubmitSuccess>(null);
  const [resetCounter, setResetCounter] = useState(0);

  const value = useMemo<IntakeFlowContextValue>(
    () => ({
      clientId,
      setClientId,
      draftId,
      setDraftId,
      consultDone,
      setConsultDone,
      consultFinal,
      setConsultFinal,
      targetMarketDone,
      setTargetMarketDone,
      targetMarketSummary,
      setTargetMarketSummary,
      peopleDone,
      setPeopleDone,
      keyPeopleSummary,
      setKeyPeopleSummary,
      submitLoading,
      setSubmitLoading,
      submitError,
      setSubmitError,
      submitSuccess,
      setSubmitSuccess,
      resetCounter,
      bumpResetCounter: () => setResetCounter((prev) => prev + 1),
    }),
    [
      clientId,
      consultDone,
      consultFinal,
      draftId,
      keyPeopleSummary,
      peopleDone,
      resetCounter,
      submitError,
      submitLoading,
      submitSuccess,
      targetMarketDone,
      targetMarketSummary,
    ]
  );

  return (
    <IntakeFlowContext.Provider value={value}>
      {children}
    </IntakeFlowContext.Provider>
  );
}

export function useIntakeFlow() {
  const ctx = useContext(IntakeFlowContext);
  if (!ctx) {
    throw new Error("useIntakeFlow must be used within IntakeFlowProvider");
  }
  return ctx;
}

