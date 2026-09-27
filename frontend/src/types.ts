export type Terms = {
  price: number;
  hours: number;
  deadline_days: number;
  daily_capacity: number;
  hourly_cost: number;
  payment: string;
  scope: string;
};
export type Option = {
  id: string;
  label: string;
  description: string;
  terms?: Terms | null;
};
export type Scenario = {
  practice_model?: "conversation" | "financial";
  id: string;
  title: string;
  eyebrow: string;
  description: string;
  duration: string;
  skill: string;
  client_name: string;
  client_role: string;
  company: string;
  briefing: string;
  objective: string;
  constraints: string[];
  baseline: Terms | null;
  priorities: { id: string; label: string; description: string }[];
  options: Option[];
  opening?: string;
};
export type TrainingConfig = {
  industry: "digital" | "it" | "consulting";
  topic: "scope" | "discount";
  difficulty: "standard" | "hard";
  tone: "collaborative" | "reserved" | "pressing";
  client_role: "project_lead" | "business_owner" | "procurement";
  goal: "deadline" | "full_scope" | "budget" | "cashflow";
  duration_minutes: 5 | 10 | 15;
  format: "text" | "voice";
  response_seconds: 0 | 45;
};
export type TrainingPreview = {
  scenario: Scenario;
  configuration: TrainingConfig;
  generation_method: "template";
  max_turns: number;
  context_key: string;
};
export type Message = {
  id: string;
  client_message_id?: string;
  client_action_id?: string;
  role: "assistant" | "user" | "system";
  text: string;
  created_at: string;
  kind?: string;
};
export type Proposal = {
  option_id: string;
  label: string;
  description?: string;
  terms?: Terms | null;
  client_status: "accepted" | "rejected";
  reason: string;
};
export type Metrics = {
  required_hours: number;
  available_hours: number;
  overflow_hours: number;
  required_days: number;
  delay_days: number;
  direct_cost: number;
  contribution: number;
  baseline_contribution: number;
  feasible: boolean;
  minimum_contribution?: number;
  violation_reasons?: string[];
};
export type Feedback = {
  title: string;
  summary: string;
  outcome: "agreement" | "feasible" | "infeasible" | "no_agreement";
  metrics: Metrics | null;
  moments: {
    title: string;
    quote: string;
    explanation: string;
    message_id?: string;
  }[];
  behaviors?: {
    id: string;
    label: string;
    status: "observed" | "not_observed";
    eligible?: boolean;
    evidence: { message_id: string; quote: string }[];
    explanation: string;
  }[];
  next_step: string;
  strengths: string[];
  improvements: string[];
};
export type ReplyChoice = {
  id: string;
  group: "explore" | "respond" | "negotiate";
  label: string;
  text: string;
};
export type ReplyMode = "rules" | "generated";
export type MentorAction = "hint" | "example" | "review";
export type MentorMode = "guided" | "independent";
export type MentorAdvice = {
  id: string;
  action: MentorAction;
  method: "rules";
  title: string;
  text: string;
  example?: string;
  message_id?: string;
  context_message_id?: string;
  created_at: string;
};
export type MentorState = {
  mode: MentorMode;
  tracking_started: boolean;
  tracked_from_start: boolean;
  used: boolean;
  counts: Record<MentorAction, number>;
  last_advice: MentorAdvice | null;
};
export type Session = {
  id: string;
  scenario: Scenario;
  priority: string;
  difficulty: "standard" | "hard";
  mode: "demo" | "live";
  reply_mode?: ReplyMode;
  status: "active" | "completed";
  created_at: string;
  messages: Message[];
  proposal: Proposal | null;
  feedback: Feedback | null;
  discovered_interests: string[];
  suggestions: string[];
  reply_choices?: ReplyChoice[];
  conversation_hint?: string;
  turns: number;
  training_config?: TrainingConfig;
  context_key?: string;
  max_turns?: number;
  extra_turns?: number;
  turn_limit?: number;
  generation_method?: "template";
  retry_of?: string;
  mentor_state?: MentorState;
};
