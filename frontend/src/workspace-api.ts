import { request } from "./api";
import type { Session, TrainingConfig, TrainingPreview } from "./types";

export type Account = {
  id: string;
  username: string;
  display_name: string;
  role: "user" | "admin";
};
export type CaseContent = {
  practice_model?: "conversation";
  title: string;
  description: string;
  briefing: string;
  objective: string;
  client_name: string;
  company: string;
  opening: string;
  configuration: TrainingConfig;
};
export type PublicCase = {
  id: string;
  revision: number;
  status: "published";
  content: CaseContent;
  published_at: string;
  updated_at: string;
};
export type AdminCase = {
  id: string;
  revision: number;
  status: "draft" | "published" | "archived";
  content: CaseContent;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  published_revision: number | null;
  has_unpublished_changes: boolean;
};

export const workspaceApi = {
  me: () => request<{ user: Account | null }>("/auth/me"),
  login: (username: string, password: string) =>
    request<{ user: Account }>("/auth/login", { username, password }),
  register: (username: string, display_name: string, password: string) =>
    request<{ user: Account }>("/auth/register", {
      username,
      display_name,
      password,
    }),
  logout: () => request<{ user: null }>("/auth/logout", {}),
  catalog: () => request<{ items: PublicCase[] }>("/catalog"),
  catalogCase: (id: string) =>
    request<{ item: PublicCase; preview: TrainingPreview }>(
      `/catalog/${encodeURIComponent(id)}`,
    ),
  startCase: (
    id: string,
    revision: number,
    mode: "demo" | "live",
    client_action_id: string,
  ) =>
    request<Session>(`/catalog/${encodeURIComponent(id)}/start`, {
      revision,
      mode,
      client_action_id,
    }),
  adminCases: () => request<{ items: AdminCase[] }>("/admin/cases"),
  createCase: (content: CaseContent, client_action_id: string) =>
    request<{ item: AdminCase }>("/admin/cases", { content, client_action_id }),
  saveCase: (id: string, revision: number, content: CaseContent) =>
    request<{ item: AdminCase }>(`/admin/cases/${encodeURIComponent(id)}`, {
      revision,
      content,
    }),
  publishCase: (id: string, revision: number) =>
    request<{ item: AdminCase }>(
      `/admin/cases/${encodeURIComponent(id)}/publish`,
      { revision },
    ),
  unpublishCase: (id: string, revision: number) =>
    request<{ item: AdminCase }>(
      `/admin/cases/${encodeURIComponent(id)}/unpublish`,
      { revision },
    ),
  archiveCase: (id: string, revision: number) =>
    request<{ item: AdminCase }>(
      `/admin/cases/${encodeURIComponent(id)}/archive`,
      { revision },
    ),
  previewCase: (content: CaseContent) =>
    request<{ preview: TrainingPreview }>("/admin/cases/preview", { content }),
};
