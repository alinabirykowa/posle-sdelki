import { ChevronDown, LoaderCircle, RotateCcw } from "lucide-react";
import type { Session } from "../types";
import {
  reviewAssistance,
  reviewExercise,
  reviewObservations,
} from "../session-review";
import "../review-cabinet.css";

export function SessionReview({
  session,
  busy,
  error,
  onRetry,
  onPractice,
}: {
  session: Session;
  busy: boolean;
  error: string;
  onRetry: () => void;
  onPractice: () => void;
}) {
  const feedback = session.feedback;
  const observations = reviewObservations(session);
  const observed = observations.filter(
    (item) => item.reviewStatus === "observed",
  );
  const exercise = reviewExercise(observations);
  const missing = observations.find(
    (item) => item.id === exercise.id && item.reviewStatus === "not_observed",
  );
  const hasReply = session.messages.some(
    (message) =>
      message.role === "user" && (!message.kind || message.kind === "message"),
  );
  if (!feedback)
    return (
      <section
        className="cabinet-review cabinet-review-empty"
        aria-labelledby="session-review-title"
      >
        <h2 id="session-review-title">Разбор разговора</h2>
        <p>
          Сохранённый разбор пока недоступен. Обновите страницу, чтобы проверить
          его ещё раз.
        </p>
        <button
          type="button"
          className="cabinet-other-practice"
          onClick={onPractice}
          disabled={busy}
        >
          Выбрать другую тренировку
        </button>
        {error && (
          <p className="cabinet-review-error" role="alert">
            {error}
          </p>
        )}
      </section>
    );

  const improvement =
    missing?.explanation ||
    (!hasReply
      ? "В этой попытке нет свободных реплик, по которым можно разобрать ваши приёмы. Начните следующий разговор своими словами."
      : feedback.improvements[0] ||
        "В сохранённом разборе нет отдельного замечания. Повторите ситуацию и проверьте, получится ли применить приёмы в другом ответе.");
  const successNotes = (
    feedback.strengths.length
      ? feedback.strengths
      : observed.map((item) => item.explanation)
  ).slice(0, 2);
  const evidenceCount = observed.reduce(
    (count, item) => count + item.evidence.length,
    0,
  );
  const outcome =
    feedback.outcome === "agreement"
      ? "Договорённость достигнута"
      : feedback.outcome === "no_agreement"
        ? "Итоговые условия не подтверждены"
        : feedback.title;

  return (
    <section
      className="cabinet-review"
      aria-labelledby="session-review-title"
      aria-busy={busy}
    >
      <header className="cabinet-review-heading">
        <h2 id="session-review-title">Разбор разговора</h2>
        <p className="cabinet-review-situation">{session.scenario.title}</p>
        <p className="cabinet-review-saved">Диалог сохранён</p>
        <p className="cabinet-review-outcome">{outcome}</p>
        <p className="cabinet-review-summary">{feedback.summary}</p>
        <p className="cabinet-review-assistance">{reviewAssistance(session)}</p>
        {(session.extra_turns ?? 0) > 0 && (
          <p className="cabinet-review-assistance">
            В этой попытке добавлены ходы: {session.extra_turns}. Повтор
            начнётся с исходного лимита.
          </p>
        )}
      </header>

      <div className="cabinet-review-findings">
        <section aria-labelledby="review-strengths-title">
          <h3 id="review-strengths-title">Что получилось</h3>
          {successNotes.length ? (
            <ul>
              {successNotes.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          ) : (
            <p>
              Пока нет подтверждённых примеров. Это описание этой попытки, а не
              оценка ваших способностей.
            </p>
          )}
          {observed.length > 0 && (
            <details className="cabinet-review-evidence">
              <summary>
                Реплики, на которых основан разбор{" "}
                <ChevronDown size={15} aria-hidden="true" />
              </summary>
              {observed.map((item) => (
                <div key={item.id}>
                  <strong>{item.label}</strong>
                  {item.evidence.map((evidence) => (
                    <blockquote
                      key={`${evidence.message_id}:${evidence.quote}`}
                    >
                      «{evidence.quote}»
                    </blockquote>
                  ))}
                </div>
              ))}
            </details>
          )}
        </section>
        <section aria-labelledby="review-improvements-title">
          <h3 id="review-improvements-title">Что улучшить</h3>
          <p>{improvement}</p>
          {observations.some(
            (item) =>
              item.id === "responded_to_objection" &&
              item.reviewStatus === "not_practiced",
          ) && (
            <p className="cabinet-review-note">
              Ответ на возражение в этой попытке не проверялся.
            </p>
          )}
        </section>
      </div>

      <section
        className="cabinet-review-practice"
        aria-labelledby="review-next-title"
      >
        <h3 id="review-next-title">В следующей попытке</h3>
        <p className="cabinet-review-focus">
          {feedback.next_step || exercise.title}
        </p>
        <details className="cabinet-review-exercise">
          <summary>
            Как потренироваться: {exercise.title.toLocaleLowerCase("ru")}{" "}
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
          <ol>
            {exercise.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <p>
            Разговорчик даст намёк или пример. Для самостоятельной попытки
            выберите «Самостоятельно» до своей первой реплики.
          </p>
        </details>
        <div className="cabinet-review-actions">
          <button
            type="button"
            className="button primary"
            disabled={busy}
            onClick={onRetry}
          >
            {busy ? (
              <LoaderCircle size={17} className="spin" aria-hidden="true" />
            ) : (
              <RotateCcw size={17} aria-hidden="true" />
            )}
            {busy ? "Готовим попытку…" : "Повторить ситуацию"}
          </button>
          <button
            type="button"
            className="cabinet-other-practice"
            disabled={busy}
            onClick={onPractice}
          >
            Выбрать другую тренировку
          </button>
        </div>
        {error && (
          <p className="cabinet-review-error" role="alert">
            {error}
          </p>
        )}
      </section>

      <div className="cabinet-review-details">
        <details>
          <summary>
            Все наблюдения и рекомендации{" "}
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
          <div className="cabinet-review-detail-body">
            {observations.map((item) => (
              <div className="cabinet-review-observation" key={item.id}>
                <strong>{item.label}</strong>
                <span>
                  {item.reviewStatus === "observed"
                    ? "Есть подтверждённый пример"
                    : item.reviewStatus === "not_observed"
                      ? "В этой попытке пример не найден"
                      : item.reviewStatus === "not_practiced"
                        ? "Не проверялось в этой попытке"
                        : "Недостаточно данных для вывода"}
                </span>
                {item.reviewStatus !== "not_practiced" && (
                  <p>{item.explanation}</p>
                )}
              </div>
            ))}
            {feedback.strengths.length > 2 && (
              <div className="cabinet-review-saved-notes">
                <strong>Ещё получилось</strong>
                <ul>
                  {feedback.strengths.slice(2).map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              </div>
            )}
            {feedback.improvements.length > 0 && (
              <div className="cabinet-review-saved-notes">
                <strong>Рекомендации из сохранённого разбора</strong>
                <ul>
                  {feedback.improvements.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              </div>
            )}
            {observations.length === 0 && (
              <p>
                В этой сохранённой попытке нет отдельных наблюдений по приёмам.
              </p>
            )}
            {evidenceCount === 0 && (
              <p className="cabinet-review-note">
                Подтверждённые цитаты для наблюдений не сохранены.
              </p>
            )}
          </div>
        </details>
        <details>
          <summary>
            Весь разговор <ChevronDown size={16} aria-hidden="true" />
          </summary>
          <div className="cabinet-review-transcript">
            {session.messages.map((message) => (
              <div key={message.id}>
                <strong>
                  {message.role === "user"
                    ? "Вы"
                    : message.role === "assistant"
                      ? session.scenario.client_name
                      : "Событие"}
                </strong>
                <p>{message.text}</p>
              </div>
            ))}
          </div>
        </details>
      </div>
      <p className="cabinet-review-method">
        Разбор опирается на сохранённые реплики этой попытки. Это наблюдения по
        учебному разговору, а не оценка профессионализма.
      </p>
    </section>
  );
}
