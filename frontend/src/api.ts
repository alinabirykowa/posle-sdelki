import type {
  Scenario,
  ReplyMode,
  Session,
  RouteStageId,
  TrainingConfig,
  TrainingPreview,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(60_000),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : "Не получилось выполнить действие. Попробуйте ещё раз.";
    throw new ApiError(detail, response.status);
  }
  if (!data || typeof data !== "object")
    throw new Error(
      "Сервер вернул неполный ответ. Обновите попытку или повторите действие.",
    );
  return data as T;
}

export const api = {
  trainingPreview: (configuration: TrainingConfig) =>
    request<TrainingPreview>("/training/preview", { configuration }),
  trainingStart: (
    configuration: TrainingConfig,
    mode: "demo" | "live",
    client_action_id: string,
    route_stage?: RouteStageId,
  ) =>
    request<Session>("/training/start", {
      configuration,
      mode,
      client_action_id,
      ...(route_stage ? { route_stage } : {}),
    }),
  scenarios: () =>
    request<{
      scenarios: Scenario[];
      live_available: boolean;
      live_reply_mode?: ReplyMode;
    }>("/scenarios"),
  sessions: () => request<{ sessions: Session[] }>("/sessions"),
  session: (id: string) =>
    request<Session>(`/sessions/${encodeURIComponent(id)}`),
  start: (
    scenario_id: string,
    priority: string,
    difficulty: "standard" | "hard",
    mode: "demo" | "live",
  ) =>
    request<Session>("/sessions", { scenario_id, priority, difficulty, mode }),
  message: (id: string, text: string, client_message_id: string) =>
    request<Session>(`/sessions/${id}/messages`, { text, client_message_id }),
  propose: (id: string, option_id: string, client_action_id: string) =>
    request<Session>(`/sessions/${id}/proposal`, {
      option_id,
      client_action_id,
    }),
  finish: (id: string, outcome: "agreement" | "no_agreement") =>
    request<Session>(`/sessions/${id}/finish`, { outcome }),
  extend: (id: string, client_action_id: string) =>
    request<{ session: Session }>(
      `/sessions/${encodeURIComponent(id)}/extend`,
      { client_action_id },
    ),
  retry: (id: string, client_action_id: string) =>
    request<Session>(`/sessions/${id}/retry`, { client_action_id }),
};

export function errorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === "TimeoutError")
    return "Сервер не успел ответить. Обновите попытку или повторите действие: уже принятое сообщение или предложение не продублируется.";
  if (error instanceof TypeError)
    return "Не удалось связаться с сервером. Проверьте соединение и повторите действие.";
  return error instanceof Error
    ? error.message
    : "Не удалось связаться с сервисом. Попробуйте ещё раз.";
}
