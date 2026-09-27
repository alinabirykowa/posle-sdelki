import { request } from "./api";
import type { MentorAction, MentorAdvice, MentorMode, Session } from "./types";

export const mentorApi = {
  advice: (
    id: string,
    action: MentorAction,
    client_action_id: string,
    message_id?: string,
  ) =>
    request<{ session: Session; advice: MentorAdvice }>(
      `/sessions/${encodeURIComponent(id)}/mentor`,
      {
        action,
        client_action_id,
        ...(message_id ? { message_id } : {}),
      },
    ),
  mode: (id: string, mode: MentorMode, client_action_id: string) =>
    request<{ session: Session }>(
      `/sessions/${encodeURIComponent(id)}/mentor-mode`,
      { mode, client_action_id },
    ),
};
