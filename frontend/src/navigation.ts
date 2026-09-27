import type { Session } from "./types";

export function sessionDestination(
  session: Pick<Session, "id" | "status">,
): string {
  return session.status === "completed"
    ? `/progress/${encodeURIComponent(session.id)}`
    : `/session/${encodeURIComponent(session.id)}`;
}

export function progressRoute(route: string): {
  active: boolean;
  reviewId?: string;
} {
  if (route === "/progress") return { active: true };
  const match = /^\/progress\/([^/?#]+)$/.exec(route);
  if (!match) return { active: false };
  try {
    return { active: true, reviewId: decodeURIComponent(match[1]) };
  } catch {
    return { active: false };
  }
}
