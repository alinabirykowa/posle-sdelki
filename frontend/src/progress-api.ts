import { request } from "./api";

export type AssistanceKind = "guided" | "independent" | "unknown";
export type SkillStatus = "observed" | "not_observed" | "not_practiced";
export type ProgressEvidence = {
  session_id: string;
  message_id: string;
  quote: string;
  assistance: AssistanceKind;
  title: string;
  created_at: string | null;
  completed_at: string | null;
};
export type ProgressSkill = {
  id: string;
  label: string;
  status: SkillStatus;
  observed_count: number;
  eligible_count: number;
  not_practiced_count: number;
  evidence: ProgressEvidence[];
};
export type PracticeEntry = {
  session_id: string;
  title: string;
  created_at: string | null;
  completed_at: string | null;
  status: "active" | "completed";
  mode: "demo" | "live";
  practice_model: string | null;
  assistance: AssistanceKind;
  mentor_used?: boolean | null;
};
export type ProgressComparisonPoint = {
  session_id: string;
  title: string;
  created_at: string | null;
  completed_at: string | null;
  mode: "demo" | "live";
  assistance: AssistanceKind;
  mentor_used?: boolean | null;
  skills: Pick<ProgressSkill, "id" | "label" | "status" | "evidence">[];
};
export type ProgressRecommendation = {
  kind: "start" | "continue" | "retry";
  label: string;
  reason: string;
  session_id: string | null;
};
export type PracticeProgress = {
  scope: "all_owner_history";
  summary: {
    total: number;
    completed: number;
    active: number;
    conversation_completed: number;
    unique_situations: number;
    legacy_completed: number;
    assistance: Record<AssistanceKind, number>;
  };
  observation_scope: {
    title: string;
    attempts: number;
    comparable: boolean;
    reason: string;
  };
  skills: ProgressSkill[];
  recent_practice: PracticeEntry[];
  latest_completed: PracticeEntry | null;
  comparison: {
    eligible: boolean;
    reason: string;
    previous: ProgressComparisonPoint | null;
    current: ProgressComparisonPoint | null;
  };
  recommendation: ProgressRecommendation;
};

export const progressApi = {
  get: () => request<PracticeProgress>("/progress"),
};
