import type { RouteStageId, TrainingConfig } from "./types";

type PendingAction = { id: string; payload: string };
type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

// Keep identifiers in memory when browser storage is unavailable. A reload in
// that environment cannot promise recovery; a mounted page still deduplicates.
export function createPendingActions(
  getStorage: () => StorageLike,
  newId: () => string,
) {
  const memory = new Map<string, PendingAction | null>();
  function read(key: string): PendingAction | null {
    if (memory.has(key)) return memory.get(key)!;
    try {
      const saved = JSON.parse(getStorage().getItem(key) || "null");
      const payload = saved?.payload ?? saved?.text; // v0.2 message drafts
      if (
        typeof saved?.id === "string" &&
        saved.id.length > 0 &&
        saved.id.length <= 100 &&
        typeof payload === "string"
      ) {
        const action = { id: saved.id, payload };
        memory.set(key, action);
        return action;
      }
    } catch {
      // Storage is optional; invalid persisted data never blocks a conversation.
    }
    return null;
  }
  return {
    read,
    get(key: string, payload: string): PendingAction {
      const previous = read(key);
      if (previous?.payload === payload) return previous;
      const next = { id: newId(), payload };
      memory.set(key, next);
      try {
        getStorage().setItem(key, JSON.stringify(next));
      } catch {
        // The in-memory identifier remains stable for a manual retry.
      }
      return next;
    },
    clear(key: string, id: string) {
      if (read(key)?.id !== id) return;
      memory.set(key, null);
      try {
        getStorage().removeItem(key);
      } catch {
        // A successful server acknowledgement is still authoritative.
      }
    },
  };
}

export const pendingActions = createPendingActions(
  () => sessionStorage,
  () => crypto.randomUUID(),
);

export function recoveredMessage(
  messages: { role: string; text: string; client_message_id?: string }[],
  pending: PendingAction | null,
) {
  return (
    !!pending &&
    messages.some(
      (message) =>
        message.role === "user" &&
        message.client_message_id === pending.id &&
        message.text === pending.payload,
    )
  );
}

export function reconcilePendingActions(
  sessionId: string,
  messages: {
    role: string;
    text: string;
    kind?: string;
    client_message_id?: string;
    client_action_id?: string;
  }[],
  actions = pendingActions,
) {
  const messageKey = `pending-message:${sessionId}`;
  const proposalKey = `pending-proposal:${sessionId}`;
  const message = actions.read(messageKey);
  const proposal = actions.read(proposalKey);
  const messageSaved = recoveredMessage(messages, message);
  const proposalSaved =
    !!proposal &&
    messages.some(
      (item) =>
        item.role === "user" &&
        item.kind === "proposal" &&
        item.client_action_id === proposal.id,
    );
  if (messageSaved && message) actions.clear(messageKey, message.id);
  if (proposalSaved && proposal) actions.clear(proposalKey, proposal.id);
  return {
    message: messageSaved ? message!.payload : null,
    proposal: proposalSaved,
  };
}

export type PendingCatalogStart = {
  key: string;
  id: string;
  user_id: string;
  case_id: string;
  revision: number;
  mode: "demo" | "live";
};

// One unresolved catalogue start per account. Keeping the case and its published
// revision here permits recovery even after that case disappears from the list.
export function readPendingCatalogStart(
  userId: string,
  actions = pendingActions,
): PendingCatalogStart | null {
  const key = `pending-catalog-start:${userId}`;
  const pending = actions.read(key);
  if (!pending) return null;
  try {
    const payload = JSON.parse(pending.payload);
    if (
      typeof payload?.case_id !== "string" ||
      !payload.case_id ||
      !Number.isSafeInteger(payload.revision) ||
      payload.revision < 1 ||
      !["demo", "live"].includes(payload.mode)
    )
      return null;
    return {
      key,
      id: pending.id,
      user_id: userId,
      case_id: payload.case_id,
      revision: payload.revision,
      mode: payload.mode,
    };
  } catch {
    return null;
  }
}

export function getPendingCatalogStart(
  userId: string,
  caseId: string,
  revision: number,
  mode: "demo" | "live",
  actions = pendingActions,
): PendingCatalogStart {
  const pending = readPendingCatalogStart(userId, actions);
  if (pending) return pending;
  const key = `pending-catalog-start:${userId}`;
  const action = actions.get(
    key,
    JSON.stringify({ case_id: caseId, revision, mode }),
  );
  return {
    key,
    id: action.id,
    user_id: userId,
    case_id: caseId,
    revision,
    mode,
  };
}

export function clearPendingCatalogStart(
  pending: PendingCatalogStart,
  actions = pendingActions,
) {
  actions.clear(pending.key, pending.id);
}

export type PendingTrainingStart = {
  key: string;
  id: string;
  configuration: TrainingConfig;
  mode: "demo" | "live";
  route_stage?: RouteStageId;
};

function isRouteStageId(value: unknown): value is RouteStageId {
  return ["discover", "explain", "objection", "independent"].includes(
    String(value),
  );
}

function isTrainingConfig(value: unknown): value is TrainingConfig {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const config = value as Record<string, unknown>;
  const options = {
    industry: ["digital", "it", "consulting"],
    topic: ["scope", "discount"],
    difficulty: ["standard", "hard"],
    tone: ["collaborative", "reserved", "pressing"],
    client_role: ["project_lead", "business_owner", "procurement"],
    goal: ["deadline", "full_scope", "budget", "cashflow"],
    duration_minutes: [5, 10, 15],
    format: ["text", "voice"],
    response_seconds: [0, 45],
  } satisfies Record<keyof TrainingConfig, readonly unknown[]>;
  if (Object.keys(config).length !== Object.keys(options).length) return false;
  if (
    !Object.entries(options).every(([field, allowed]) =>
      (allowed as readonly unknown[]).includes(config[field]),
    )
  )
    return false;
  return config.topic === "scope"
    ? config.goal === "deadline" || config.goal === "full_scope"
    : config.goal === "budget" || config.goal === "cashflow";
}

// One unresolved request per identity. A changed form must never silently
// overwrite the request whose server response was lost. Clearing it explicitly
// starts a fresh intent; the old global key has no verifiable owner to adopt.
export function readPendingTrainingStart(
  identityKey: string,
  actions = pendingActions,
): PendingTrainingStart | null {
  const key = `pending-training-start:${identityKey}`;
  const pending = actions.read(key);
  if (!pending || !pending.id.trim()) return null;
  try {
    const payload: unknown = JSON.parse(pending.payload);
    if (!payload || typeof payload !== "object" || Array.isArray(payload))
      return null;
    const record = payload as Record<string, unknown>;
    const keys = Object.keys(record);
    if (
      !(
        keys.length === 2 ||
        (keys.length === 3 && isRouteStageId(record.route_stage))
      ) ||
      !isTrainingConfig(record.configuration) ||
      (record.mode !== "demo" && record.mode !== "live")
    )
      return null;
    return {
      key,
      id: pending.id,
      configuration: record.configuration,
      mode: record.mode,
      ...(isRouteStageId(record.route_stage)
        ? { route_stage: record.route_stage }
        : {}),
    };
  } catch {
    return null;
  }
}

export function getPendingTrainingStart(
  identityKey: string,
  configuration: TrainingConfig,
  mode: "demo" | "live",
  actions = pendingActions,
  routeStage?: RouteStageId,
): PendingTrainingStart {
  const pending = readPendingTrainingStart(identityKey, actions);
  if (pending) return pending;
  const key = `pending-training-start:${identityKey}`;
  const invalid = actions.read(key);
  if (invalid) actions.clear(key, invalid.id);
  const payload = {
    configuration,
    mode,
    ...(routeStage ? { route_stage: routeStage } : {}),
  };
  const action = actions.get(key, JSON.stringify(payload));
  return {
    key,
    id: action.id,
    configuration: { ...configuration },
    mode,
    ...(routeStage ? { route_stage: routeStage } : {}),
  };
}

export function clearPendingTrainingStart(
  pending: PendingTrainingStart,
  actions = pendingActions,
) {
  actions.clear(pending.key, pending.id);
}
