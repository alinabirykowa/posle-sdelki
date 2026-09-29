import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(
  new URL("../src/session-review.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
  },
});
const {
  reviewObservations,
  reviewExercise,
  reviewAssistance,
  reviewUtterances,
  reviewSummary,
  utteranceStatusLabel,
  highlightedQuote,
  verdictLabel,
  responseStatusLabel,
} = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

function behavior(id, status = "not_observed", eligible = true, evidence = []) {
  return {
    id,
    label: id,
    status,
    eligible,
    evidence,
    explanation: "Сохранённое наблюдение",
  };
}
function session(behaviors, messages = []) {
  return { messages, feedback: { behaviors } };
}
const reply = {
  id: "reply",
  role: "user",
  kind: "message",
  text: "Расскажите, что для вас важно?",
};
const proof = { message_id: reply.id, quote: "что для вас важно?" };

test("preserves an exact saved quote linked to one free user reply", () => {
  const observations = reviewObservations(
    session(
      [behavior("clarified_need", "observed", true, [proof, proof])],
      [reply],
    ),
  );
  assert.equal(observations[0].reviewStatus, "observed");
  assert.deepEqual(observations[0].evidence, [proof]);
});

test("never presents fabricated, ambiguous, client or proposal quotes as skill evidence", () => {
  for (const messages of [
    [],
    [{ ...reply, role: "assistant" }],
    [{ ...reply, kind: "proposal" }],
    [reply, { ...reply }],
    [{ ...reply, text: "Другая реплика" }],
  ]) {
    const [observation] = reviewObservations(
      session(
        [behavior("clarified_need", "observed", true, [proof])],
        messages,
      ),
    );
    assert.equal(observation.reviewStatus, "unknown");
    assert.deepEqual(observation.evidence, []);
  }
});

test("chooses the first missing eligible skill in learning order, not response array order", () => {
  const observations = reviewObservations(
    session([
      behavior("responded_to_objection"),
      behavior("justified_proposal"),
      behavior("clarified_need"),
    ]),
  );
  assert.equal(reviewExercise(observations).id, "clarified_need");
  assert.equal(
    reviewExercise(observations.filter((item) => item.id !== "clarified_need"))
      .id,
    "justified_proposal",
  );
  assert.equal(
    reviewExercise(observations.slice(0, 1)).id,
    "responded_to_objection",
  );
});

test("does not call absence of an objection opportunity a failed skill", () => {
  const observations = reviewObservations(
    session(
      [
        behavior("clarified_need", "observed", true, [proof]),
        behavior("responded_to_objection", "not_observed", false),
      ],
      [reply],
    ),
  );
  assert.equal(observations[1].reviewStatus, "not_practiced");
  assert.equal(reviewExercise(observations).id, "consolidate");
});

test("missing eligibility in old feedback stays unknown instead of penalizing the participant", () => {
  const old = behavior("responded_to_objection");
  delete old.eligible;
  const [observation] = reviewObservations(session([old]));
  assert.equal(observation.reviewStatus, "unknown");
  assert.equal(reviewExercise([observation]).id, "prepare");
});

test("old valid quoted evidence remains visible without inventing an opportunity flag", () => {
  const old = behavior("clarified_need", "observed", true, [proof]);
  delete old.eligible;
  const [observation] = reviewObservations(session([old], [reply]));
  assert.equal(observation.reviewStatus, "observed");
  assert.equal(observation.eligible, undefined);
});

test("empty or unavailable observations suggest collecting evidence, not a failure score", () => {
  for (const state of [
    { messages: [], feedback: null },
    session([]),
    session([behavior("clarified_need", "not_observed", false)]),
  ]) {
    assert.equal(reviewExercise(reviewObservations(state)).id, "prepare");
  }
});

test("assistance copy separates unknown, available help, used help and independent practice", () => {
  const state = {
    tracked_from_start: true,
    tracking_started: true,
    mode: "guided",
    used: false,
    counts: { hint: 0, example: 0, review: 0 },
  };
  assert.match(reviewAssistance({}), /Нет полных данных/);
  assert.match(
    reviewAssistance({ mentor_state: { ...state, tracking_started: false } }),
    /Нет полных данных/,
  );
  assert.match(
    reviewAssistance({ mentor_state: state }),
    /подсказки не запрашивались/,
  );
  assert.match(
    reviewAssistance({ mentor_state: { ...state, mode: "independent" } }),
    /Самостоятельная/,
  );
  assert.match(
    reviewAssistance({
      mentor_state: { ...state, mode: "independent", used: true },
    }),
    /Использованы подсказки/,
  );
  assert.match(
    reviewAssistance({
      mentor_state: { ...state, counts: { ...state.counts, hint: 1 } },
    }),
    /Использованы подсказки/,
  );
});

test("shows one verbatim review per user turn and validates linked context", () => {
  const messages = [
    { id: "client", role: "assistant", text: "Что для вас важнее?" },
    { id: "first", role: "user", text: "Важно сохранить срок." },
    {
      id: "second",
      role: "user",
      text: "Потому что запуск связан с событием.",
    },
  ];
  const feedback = {
    review_method: "rules",
    review_version: 3,
    utterance_reviews: messages.slice(1).map((message) => ({
      message_id: message.id,
      quote: message.text,
      status: "strong",
      verdict: "correct",
      rule: "Ясная позиция",
      explanation: "Указана причина.",
      improved_reply: "Проверьте приоритет.",
      issues: [],
      response_status: "answered",
      response_explanation: "Клиентский вопрос получил ответ.",
      delivery: {
        tone: "neutral",
        quote: "",
        label: "Тон не оценён",
        explanation: "В этой реплике нет однозначного маркера.",
      },
      problems: [],
      context: { message_id: "client", quote: "Что для вас важнее?" },
    })),
    review_summary: {
      assessment: "Разобрано две реплики.",
      strengths: ["Назван интерес."],
      improvements: [],
      practice: ["Проверьте понимание."],
      next_training: "Повторите сценарий.",
    },
  };
  const source = { messages, feedback };
  const cards = reviewUtterances(source);
  assert.deepEqual(
    cards.map((item) => item.quote),
    messages.slice(1).map((item) => item.text),
  );
  assert.equal(cards[0].context.quote, "Что для вас важнее?");
  assert.equal(reviewSummary(source).next_training, "Повторите сценарий.");
  assert.equal(utteranceStatusLabel(cards[0]), "Сильная");
});

test("fails closed when any quote is missing, ambiguous or mismatched", () => {
  const source = {
    messages: [reply],
    feedback: {
      review_method: "rules",
      review_version: 3,
      utterance_reviews: [],
      review_summary: {
        assessment: "Есть разбор.",
        strengths: [],
        improvements: [],
        practice: [],
        next_training: "Повторите.",
      },
    },
  };
  assert.equal(reviewUtterances(source)[0].status, "unknown");
  assert.equal(reviewSummary(source), null);
});

test("highlights only an exact server-identified error phrase and labels its verdict", () => {
  const source = {
    messages: [
      { id: "bad", role: "user", text: "Вы идиот, но срок не подходит." },
    ],
    feedback: {
      review_method: "rules",
      review_version: 3,
      utterance_reviews: [
        {
          message_id: "bad",
          quote: "Вы идиот, но срок не подходит.",
          status: "unclear",
          verdict: "incorrect",
          rule: "Оскорбление недопустимо",
          explanation: "Слово направлено на собеседника.",
          improved_reply: "Опишите несогласие с условием.",
          issues: ["rudeness"],
          response_status: "not_question",
          response_explanation: "Клиент не задавал прямой вопрос.",
          delivery: {
            tone: "hostile",
            quote: "идиот",
            label: "Резкая формулировка",
            explanation: "Личная атака.",
          },
          problems: [
            {
              quote: "идиот",
              title: "Оскорбление",
              explanation: "Это личная оценка собеседника.",
              improved_reply: "Уберите личную оценку.",
            },
          ],
          context: null,
        },
      ],
      review_summary: {
        assessment: "Есть ошибка.",
        strengths: [],
        improvements: ["Оскорбление"],
        practice: [],
        next_training: "Повторите.",
      },
    },
  };
  const [card] = reviewUtterances(source);
  assert.deepEqual(highlightedQuote(card), [
    { text: "Вы ", issue: false },
    { text: "идиот", issue: true },
    { text: ", но срок не подходит.", issue: false },
  ]);
  assert.equal(verdictLabel(card), "Ошибка");
  assert.equal(
    responseStatusLabel(card.response_status),
    "Клиент не задавал прямой вопрос",
  );
});

test("highlights repeated occurrences of the same problematic word", () => {
  assert.deepEqual(
    highlightedQuote({
      quote: "Говно и снова говно.",
      problems: [
        { quote: "Говно" },
        { quote: "говно" },
      ],
    }),
    [
      { text: "Говно", issue: true },
      { text: " и снова ", issue: false },
      { text: "говно", issue: true },
      { text: ".", issue: false },
    ],
  );
});
