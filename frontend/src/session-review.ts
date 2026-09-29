import type {
  Feedback,
  ReviewSummary,
  Session,
  UtteranceReview,
} from "./types";

export type ReviewedUtterance = Omit<UtteranceReview, "status"> & {
  status: UtteranceReview["status"] | "unknown";
  sequence: number;
};
export type HighlightSegment = { text: string; issue: boolean };

/** Keep occurrences in transcript order, never reconstruct or shorten a quote. */
export function reviewUtterances(session: Session): ReviewedUtterance[] {
  const feedback = session.feedback;
  const saved = Array.isArray(feedback?.utterance_reviews)
    ? feedback.utterance_reviews
    : [];
  let sequence = 0;
  return session.messages.flatMap((message, index) => {
    if (message.role !== "user") return [];
    sequence += 1;
    const fallback: ReviewedUtterance = {
      sequence,
      message_id: message.id,
      quote: message.text,
      status: "unknown",
      verdict: "uncertain",
      rule: "Для вывода нужны подтверждённые данные",
      explanation:
        "Не удалось сопоставить сохранённый разбор с этой репликой. Её качество не оценивается.",
      improved_reply: "",
      issues: [],
      response_status: "unclear",
      response_explanation: "Для этой реплики нет проверенного разбора.",
      delivery: {
        tone: "neutral",
        quote: "",
        label: "Нет проверенного разбора формулировки",
        explanation:
          "Не удалось проверить влияние формулировки на ход разговора.",
      },
      problems: [],
      context: null,
    };
    const candidates = saved.filter((item) => item?.message_id === message.id);
    const review = candidates.length === 1 ? candidates[0] : undefined;
    if (
      feedback?.review_method !== "rules" ||
      feedback.review_version !== 3 ||
      session.messages.filter((item) => item.id === message.id).length !== 1 ||
      !review ||
      review.quote !== message.text ||
      !["strong", "improve", "unclear"].includes(review.status) ||
      ![review.rule, review.explanation, review.improved_reply].every(
        (value) => typeof value === "string" && value.trim().length > 0,
      ) ||
      !["correct", "needs_improvement", "incorrect", "uncertain"].includes(
        review.verdict,
      ) ||
      !["answered", "partial", "missed", "not_question", "unclear"].includes(
        review.response_status,
      ) ||
      typeof review.response_explanation !== "string" ||
      !review.response_explanation.trim() ||
      !review.delivery ||
      !["hostile", "constructive", "neutral"].includes(review.delivery.tone) ||
      ![review.delivery.label, review.delivery.explanation].every(
        (value) => typeof value === "string" && value.trim(),
      ) ||
      typeof review.delivery.quote !== "string" ||
      (review.delivery.quote &&
        !message.text.includes(review.delivery.quote)) ||
      !Array.isArray(review.issues) ||
      !review.issues.every((value) => typeof value === "string") ||
      !Array.isArray(review.problems) ||
      !review.problems.every(
        (problem) =>
          problem &&
          typeof problem.quote === "string" &&
          problem.quote.trim() &&
          message.text.includes(problem.quote) &&
          [problem.title, problem.explanation, problem.improved_reply].every(
            (value) => typeof value === "string" && value.trim(),
          ),
      )
    )
      return [fallback];

    if (review.context) {
      const context = review.context;
      const matches = session.messages.filter(
        (item) => item.id === context.message_id,
      );
      const prior = matches.length === 1 ? matches[0] : undefined;
      if (
        !prior ||
        prior.role !== "assistant" ||
        session.messages.indexOf(prior) >= index ||
        prior.text !== context.quote
      )
        return [fallback];
    }
    return [{ ...review, sequence, context: review.context ?? null }];
  });
}

/** An aggregate cannot be trusted when any of its underlying cards is missing. */
export function reviewSummary(session: Session): ReviewSummary | null {
  const feedback = session.feedback;
  const summary = feedback?.review_summary;
  if (
    feedback?.review_method !== "rules" ||
    feedback.review_version !== 3 ||
    !summary ||
    ![summary.assessment, summary.next_training].every(
      (value) => typeof value === "string" && value.trim().length > 0,
    ) ||
    ![summary.strengths, summary.improvements, summary.practice].every(
      (items) =>
        Array.isArray(items) &&
        items.every((value) => typeof value === "string" && value.trim()),
    ) ||
    reviewUtterances(session).some((item) => item.status === "unknown")
  )
    return null;
  return summary;
}

/** Split the verbatim answer around spans that the server marked as issues. */
export function highlightedQuote(item: ReviewedUtterance): HighlightSegment[] {
  const occurrences = new Map<string, number>();
  const spans = item.problems
    .map((problem) => {
      const occurrence = occurrences.get(problem.quote) ?? 0;
      occurrences.set(problem.quote, occurrence + 1);
      let start = -1;
      let from = 0;
      for (let index = 0; index <= occurrence; index += 1) {
        start = item.quote.indexOf(problem.quote, from);
        if (start < 0) break;
        from = start + problem.quote.length;
      }
      return start < 0 ? null : { start, end: start + problem.quote.length };
    })
    .filter((span): span is { start: number; end: number } => span !== null)
    .sort((left, right) => left.start - right.start);
  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue;
    if (span.start > cursor)
      segments.push({
        text: item.quote.slice(cursor, span.start),
        issue: false,
      });
    segments.push({
      text: item.quote.slice(span.start, span.end),
      issue: true,
    });
    cursor = span.end;
  }
  if (cursor < item.quote.length)
    segments.push({ text: item.quote.slice(cursor), issue: false });
  if (!segments.length) segments.push({ text: item.quote, issue: false });
  return segments;
}

export function verdictLabel(item: ReviewedUtterance): string {
  if (item.status === "unknown" || item.verdict === "uncertain")
    return "Нужен контекст";
  if (item.verdict === "incorrect") return "Ошибка";
  if (item.verdict === "needs_improvement") return "Нужно доработать";
  return "Корректно";
}

export function responseStatusLabel(
  status: UtteranceReview["response_status"],
): string {
  return {
    answered: "На вопрос ответили",
    partial: "Ответ неполный",
    missed: "Вопрос остался без ответа",
    not_question: "Клиент не задавал прямой вопрос",
    unclear: "Ответ нельзя проверить",
  }[status];
}

export function utteranceStatusLabel(item: ReviewedUtterance): string {
  if (item.status === "unknown") return "Разбор недоступен";
  if (item.issues.includes("template_choice"))
    return "Можно улучшить · готовый вариант";
  if (item.issues.includes("insufficient_context"))
    return "Недостаточно контекста";
  if (item.status === "strong") return "Сильная";
  if (item.status === "improve") return "Можно улучшить";
  return "Непонятная / неуместная";
}

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
