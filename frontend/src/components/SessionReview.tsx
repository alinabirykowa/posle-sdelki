import { Award, Check, LoaderCircle, RotateCcw, Target } from "lucide-react";
import type { Session } from "../types";
import { reviewAssistance, reviewObservations } from "../session-review";
import { ROUTE_STAGE_GUIDANCE } from "../progress-api";
import { UtteranceReviewCards } from "./UtteranceReviewCards";
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

  const outcome =
    feedback.outcome === "agreement"
      ? "Соглашение подтверждено"
      : feedback.outcome === "no_agreement"
        ? "Разговор завершён без соглашения"
        : feedback.title;
  const observations = reviewObservations(session);
  const earned = observations.filter(
    (item) => item.reviewStatus === "observed",
  );
  const nextGoal = observations.find(
    (item) => item.reviewStatus === "not_observed",
  );
  const hasUnknown = observations.some(
    (item) => item.reviewStatus === "unknown",
  );

  return (
    <section
      className="cabinet-review"
      aria-labelledby="session-review-title"
      aria-busy={busy}
    >
      <header className="cabinet-review-heading">
        <h2 id="session-review-title">Разбор разговора</h2>
        <p className="cabinet-review-situation">{session.scenario.title}</p>
        <p className="cabinet-review-outcome">{outcome}</p>
        {session.route_stage && (
          <div className="cabinet-review-goal">
            <strong>
              Цель попытки · {ROUTE_STAGE_GUIDANCE[session.route_stage].title}
            </strong>
            <p>{ROUTE_STAGE_GUIDANCE[session.route_stage].goal}</p>
          </div>
        )}
        <p className="cabinet-review-assistance">{reviewAssistance(session)}</p>
        {(session.extra_turns ?? 0) > 0 && (
          <p className="cabinet-review-assistance">
            В этой попытке добавлены ходы: {session.extra_turns}. Повтор
            начнётся с исходного лимита.
          </p>
        )}
      </header>

      <section
        className="review-route-recap"
        aria-labelledby="review-route-title"
      >
        <div className="review-route-recap-heading">
          <Award size={18} aria-hidden="true" />
          <div>
            <h3 id="review-route-title">Отметки за эту попытку</h3>
            <p>
              Они появляются только для приёмов, подтверждённых вашими
              репликами.
            </p>
          </div>
        </div>
        {earned.length > 0 ? (
          <ul className="review-route-badges">
            {earned.map((item) => (
              <li key={item.id}>
                <Check size={14} aria-hidden="true" />
                <span>{item.label}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="review-route-empty">
            {hasUnknown
              ? "Для части навыков не хватило проверяемых данных. В разборе ниже показано, что известно по каждой реплике."
              : "В этой попытке пока нет подтверждённых отметок. Ниже можно посмотреть, что улучшить в ответах."}
          </p>
        )}
        {nextGoal && (
          <p className="review-route-next">
            <Target size={15} aria-hidden="true" />
            <span>
              Следующая цель маршрута: <strong>{nextGoal.label}</strong>
            </span>
          </p>
        )}
      </section>

      <UtteranceReviewCards session={session} />

      <section
        className="cabinet-review-practice"
        aria-label="Дальнейшие действия"
      >
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
            {busy
              ? "Готовим попытку…"
              : session.route_stage
                ? `Повторить этап: ${ROUTE_STAGE_GUIDANCE[session.route_stage].title}`
                : "Повторить ситуацию"}
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
    </section>
  );
}
