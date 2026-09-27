import type { Feedback, Session } from "./types";

type SavedBehavior = NonNullable<Feedback["behaviors"]>[number] & {
  eligible?: boolean;
};
export type ReviewObservation = SavedBehavior & {
  reviewStatus: "observed" | "not_observed" | "not_practiced" | "unknown";
};
export type ReviewExercise = {
  id:
    | "clarified_need"
    | "justified_proposal"
    | "responded_to_objection"
    | "prepare"
    | "consolidate";
  title: string;
  steps: string[];
};

/** Quotes must still resolve to an unambiguous free reply in this transcript. */
export function reviewObservations(session: Session): ReviewObservation[] {
  return (session.feedback?.behaviors || []).map((behavior: SavedBehavior) => {
    const seen = new Set<string>();
    const evidence = behavior.evidence.filter((item) => {
      const matches = session.messages.filter(
        (message) => message.id === item.message_id,
      );
      const message = matches.length === 1 ? matches[0] : undefined;
      const key = `${item.message_id}:${item.quote}`;
      if (
        !message ||
        message.role !== "user" ||
        (message.kind && message.kind !== "message") ||
        !item.quote.trim() ||
        !message.text.includes(item.quote) ||
        seen.has(key)
      )
        return false;
      seen.add(key);
      return true;
    });
    const reviewStatus =
      behavior.eligible === false
        ? "not_practiced"
        : behavior.status === "observed" && evidence.length > 0
          ? "observed"
          : behavior.eligible === true && behavior.status === "not_observed"
            ? "not_observed"
            : "unknown";
    return { ...behavior, evidence, reviewStatus };
  });
}

const exercises: Record<ReviewExercise["id"], ReviewExercise> = {
  clarified_need: {
    id: "clarified_need",
    title: "Сначала вопрос, потом предложение",
    steps: [
      "До предложения задайте открытый вопрос о результате и ограничениях клиента.",
      "Перескажите услышанное одной фразой и проверьте, верно ли поняли.",
      "Опирайтесь на этот ответ, когда предложите решение.",
    ],
  },
  justified_proposal: {
    id: "justified_proposal",
    title: "Объясните пользу своего варианта",
    steps: [
      "Назовите важную для клиента задачу, о которой он уже рассказал.",
      "Свяжите с ней предложение: «Предлагаю …, потому что это поможет …».",
      "Спросите, что в этом варианте подходит, а что стоит изменить.",
    ],
  },
  responded_to_objection: {
    id: "responded_to_objection",
    title: "Разберите причину отказа",
    steps: [
      "Если клиент откажет, сначала уточните, что именно его не устроило.",
      "Предложите изменение и объясните, как оно учитывает эту причину.",
      "Проверьте, снимает ли новый вариант возражение.",
    ],
  },
  prepare: {
    id: "prepare",
    title: "Дайте разбору материал",
    steps: [
      "Начните разговор со своего вопроса о задаче клиента.",
      "Ответьте на его реплику своими словами и объясните одно предложение.",
      "Завершите попытку, чтобы увидеть наблюдения по этим репликам.",
    ],
  },
  consolidate: {
    id: "consolidate",
    title: "Закрепите приёмы в новом ответе",
    steps: [
      "Повторите ситуацию и сформулируйте вопрос или аргумент иначе.",
      "В конце кратко подведите итог и уточните следующий шаг.",
      "После разговора сверьте новые реплики с этим разбором.",
    ],
  },
};

export function reviewExercise(
  observations: ReviewObservation[],
): ReviewExercise {
  for (const id of [
    "clarified_need",
    "justified_proposal",
    "responded_to_objection",
  ] as const) {
    if (
      observations.some(
        (item) => item.id === id && item.reviewStatus === "not_observed",
      )
    )
      return exercises[id];
  }
  return observations.some((item) => item.reviewStatus === "observed")
    ? exercises.consolidate
    : exercises.prepare;
}

export function reviewAssistance(session: Session): string {
  const state = session.mentor_state;
  if (!state?.tracked_from_start || !state.tracking_started)
    return "Нет полных данных об использовании помощи";
  if (state.used || Object.values(state.counts).some((count) => count > 0))
    return "Использованы подсказки Разговорчика";
  return state.mode === "independent"
    ? "Самостоятельная попытка"
    : "Режим с помощником; подсказки не запрашивались";
}
