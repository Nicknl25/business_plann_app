import type React from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { consultStorage } from "./consultStorage";

export type SubmitSuccess = {
  clientId: string;
  intakeSubmissionId?: string;
} | null;

export type IntakeEditSection = "ops" | "targetMarket" | "people" | "financials" | null;

type IntakeFlowContextValue = {
  planStarted: boolean;
  setPlanStarted: (value: boolean) => void;

  editSection: IntakeEditSection;
  setEditSection: (value: IntakeEditSection) => void;

  opsConfirmed: boolean;
  setOpsConfirmed: (value: boolean) => void;
  targetMarketConfirmed: boolean;
  setTargetMarketConfirmed: (value: boolean) => void;
  peopleConfirmed: boolean;
  setPeopleConfirmed: (value: boolean) => void;
  financialsConfirmed: boolean;
  setFinancialsConfirmed: (value: boolean) => void;

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

  financialsDone: boolean;
  setFinancialsDone: (value: boolean) => void;

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
  const [planStarted, setPlanStarted] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.sessionStorage.getItem("intake_plan_started") === "1";
    } catch {
      return false;
    }
  });
  const [editSection, setEditSection] = useState<IntakeEditSection>(null);
  const [opsConfirmed, setOpsConfirmed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.sessionStorage.getItem("intake_ops_confirmed") === "1";
    } catch {
      return false;
    }
  });
  const [targetMarketConfirmed, setTargetMarketConfirmed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.sessionStorage.getItem("intake_target_market_confirmed") === "1";
    } catch {
      return false;
    }
  });
  const [peopleConfirmed, setPeopleConfirmed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.sessionStorage.getItem("intake_people_confirmed") === "1";
    } catch {
      return false;
    }
  });
  const [financialsConfirmed, setFinancialsConfirmed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.sessionStorage.getItem("intake_financials_confirmed") === "1";
    } catch {
      return false;
    }
  });
  const [clientId, setClientId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      return consultStorage.getClientId();
    } catch {
      return null;
    }
  });
  const [draftId, setDraftId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      return consultStorage.getDraftId();
    } catch {
      return null;
    }
  });
  const [consultDone, setConsultDone] = useState(false);
  const [consultFinal, setConsultFinal] = useState<any | null>(null);
  const [targetMarketDone, setTargetMarketDone] = useState(false);
  const [targetMarketSummary, setTargetMarketSummary] = useState<string | null>(
    null
  );
  const [peopleDone, setPeopleDone] = useState(false);
  const [keyPeopleSummary, setKeyPeopleSummary] = useState<string | null>(null);
  const [financialsDone, setFinancialsDone] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<SubmitSuccess>(null);
  const [resetCounter, setResetCounter] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem("intake_plan_started", planStarted ? "1" : "0");
    } catch {
      // ignore
    }
  }, [planStarted]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem("intake_ops_confirmed", opsConfirmed ? "1" : "0");
      window.sessionStorage.setItem(
        "intake_target_market_confirmed",
        targetMarketConfirmed ? "1" : "0"
      );
      window.sessionStorage.setItem(
        "intake_people_confirmed",
        peopleConfirmed ? "1" : "0"
      );
      window.sessionStorage.setItem(
        "intake_financials_confirmed",
        financialsConfirmed ? "1" : "0"
      );
    } catch {
      // ignore
    }
  }, [financialsConfirmed, opsConfirmed, peopleConfirmed, targetMarketConfirmed]);

  const value = useMemo<IntakeFlowContextValue>(
    () => ({
      planStarted,
      setPlanStarted,
      editSection,
      setEditSection,
      opsConfirmed,
      setOpsConfirmed,
      targetMarketConfirmed,
      setTargetMarketConfirmed,
      peopleConfirmed,
      setPeopleConfirmed,
      financialsConfirmed,
      setFinancialsConfirmed,
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
      financialsDone,
      setFinancialsDone,
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
      planStarted,
      editSection,
      opsConfirmed,
      targetMarketConfirmed,
      peopleConfirmed,
      financialsConfirmed,
      clientId,
      consultDone,
      consultFinal,
      draftId,
      financialsDone,
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
