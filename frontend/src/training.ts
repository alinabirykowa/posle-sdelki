import type { Session } from "./types";

export function assistanceCategory(
  session: Session,
): "guided" | "independent" | "unknown" {
  const state = session.mentor_state;
  if (!state?.tracked_from_start) return "unknown";
  return state.used || Object.values(state.counts).some((count) => count > 0)
    ? "guided"
    : "independent";
}

export function assistanceLabel(session: Session): string {
  const category = assistanceCategory(session);
  if (category === "unknown")
    return "Использование подсказок в этой попытке учтено не полностью";
  return category === "guided"
    ? "Использованы подсказки наставника"
    : "Без подсказок наставника";
}

/** Retries are comparable only when the saved business context is identical. */
export function sameTrainingContext(a: Session, b: Session): boolean {
  if (
    (a.max_turns ?? 30) !== (b.max_turns ?? 30) ||
    (a.extra_turns ?? 0) !== (b.extra_turns ?? 0)
  )
    return false;
  const assistance = assistanceCategory(a);
  if (assistance === "unknown" || assistance !== assistanceCategory(b))
    return false;
  if (a.mentor_state?.mode !== b.mentor_state?.mode) return false;
  if (a.scenario.practice_model !== b.scenario.practice_model) return false;
  const sameLegacySettings =
    a.scenario.id === b.scenario.id &&
    a.priority === b.priority &&
    a.difficulty === b.difficulty &&
    a.mode === b.mode &&
    (a.reply_mode ?? "rules") === (b.reply_mode ?? "rules");
  if (!sameLegacySettings) return false;

  const configuredA = Boolean(a.training_config || a.context_key);
  const configuredB = Boolean(b.training_config || b.context_key);
  if (!configuredA && !configuredB) return true;
  // Fail closed if an incomplete response omits a configured session's key.
  return Boolean(
    configuredA &&
    configuredB &&
    a.context_key &&
    b.context_key &&
    a.context_key === b.context_key,
  );
}

export function trainingSummary(session: Session): string {
  const config = session.training_config;
  if (!config) return "";
  const industry = {
    digital: "Диджитал-агентство",
    it: "IT-услуги",
    consulting: "Консалтинг",
  }[config.industry];
  const tone = {
    collaborative: "Открытый диалог",
    reserved: "Сдержанный клиент",
    pressing: "Клиент давит",
  }[config.tone];
  return [
    industry,
    config.format === "voice" ? "Голос" : "Переписка",
    `${config.duration_minutes} мин`,
    tone,
  ].join(" · ");
}
