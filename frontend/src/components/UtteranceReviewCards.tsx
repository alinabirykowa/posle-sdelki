import type { Session } from "../types";
import {
  highlightedQuote,
  responseStatusLabel,
  reviewSummary,
  reviewUtterances,
  verdictLabel,
} from "../session-review";
import "../review-cabinet.css";

function ReviewQuote({
  item,
}: {
  item: ReturnType<typeof reviewUtterances>[number];
}) {
  return (
    <blockquote className="turn-answer-quote">
      {highlightedQuote(item).map((part, index) =>
        part.issue ? (
          <mark key={index} className="turn-problem-word">
            {part.text}
          </mark>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </blockquote>
  );
}

function counts(reviews: ReturnType<typeof reviewUtterances>) {
  return reviews.reduce(
    (total, item) => {
      if (item.issues.includes("template_choice")) return total;
      if (item.verdict === "correct") total.correct += 1;
      else if (item.verdict === "incorrect") total.incorrect += 1;
      else if (item.verdict === "needs_improvement") total.improve += 1;
      else total.uncertain += 1;
      return total;
    },
    { correct: 0, improve: 0, incorrect: 0, uncertain: 0 },
  );
}

export function UtteranceReviewCards({ session }: { session: Session }) {
  const utterances = reviewUtterances(session);
  const summary = reviewSummary(session);
  const totals = counts(utterances);
  return (
    <section className="turn-review" aria-labelledby="turn-review-title">
      <header className="turn-review-header">
        <div>
          <h2 id="turn-review-title">Разбор по ходам</h2>
          <p>
            Каждый ответ проверен отдельно: по вопросу клиента, деловому тону и
            ясности формулировки.
          </p>
        </div>
        <span className="turn-review-total">
          {utterances.length} {utterances.length === 1 ? "ход" : "ходов"}
        </span>
      </header>

      <div className="turn-review-score" aria-label="Сводка ответов">
        <span className="score-correct">
          <b>{totals.correct}</b> корректно
        </span>
        <span className="score-improve">
          <b>{totals.improve}</b> доработать
        </span>
        <span className="score-incorrect">
          <b>{totals.incorrect}</b> ошибка
        </span>
        <span className="score-uncertain">
          <b>{totals.uncertain}</b> контекст
        </span>
      </div>
      {summary && (
        <p className="turn-review-assessment">{summary.assessment}</p>
      )}

      {utterances.length ? (
        <ol className="turn-list">
          {utterances.map((item) => {
            const tone =
              item.verdict === "correct"
                ? "correct"
                : item.verdict === "incorrect"
                  ? "incorrect"
                  : item.verdict === "uncertain" || item.status === "unknown"
                    ? "uncertain"
                    : "improve";
            const mainProblem = item.problems[0];
            return (
              <li
                className={`turn-card turn-${tone}`}
                key={`${item.sequence}:${item.message_id}`}
              >
                <div className="turn-card-heading">
                  <span className="turn-number">
                    Ход {String(item.sequence).padStart(2, "0")}
                  </span>
                  <span className={`turn-verdict verdict-${tone}`}>
                    {verdictLabel(item)}
                  </span>
                </div>

                {item.context && (
                  <div className="turn-client-prompt">
                    <span>{session.scenario.client_name}</span>
                    <p>{item.context.quote}</p>
                  </div>
                )}

                <div className="turn-participant-answer">
                  <span>Ваш ответ</span>
                  <ReviewQuote item={item} />
                </div>

                <div
                  className={`turn-response-check response-${item.response_status}`}
                >
                  <strong>{responseStatusLabel(item.response_status)}</strong>
                  <p>{item.response_explanation}</p>
                </div>

                <div className={`turn-delivery delivery-${item.delivery.tone}`}>
                  <strong>{item.delivery.label}</strong>
                  <p>
                    {item.delivery.quote && <mark>{item.delivery.quote}</mark>}
                    {item.delivery.quote ? " — " : ""}
                    {item.delivery.explanation}
                  </p>
                </div>

                <div className="turn-reason">
                  <h3>
                    {mainProblem
                      ? mainProblem.title
                      : tone === "correct"
                        ? "Что сработало"
                        : item.rule}
                  </h3>
                  <p>{mainProblem?.explanation || item.explanation}</p>
                  {item.problems.length > 1 && (
                    <ul className="turn-more-problems">
                      {item.problems.slice(1).map((problem, index) => (
                        <li key={`${problem.quote}:${index}`}>
                          <mark className="turn-problem-word">
                            {problem.quote}
                          </mark>
                          <span>
                            {problem.title}: {problem.explanation}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {item.problems.length === 0 && tone === "correct" && (
                    <p className="turn-no-problem">
                      Явной ошибки в этой реплике не найдено.
                    </p>
                  )}
                </div>

                <div className="turn-better-reply">
                  <span>
                    {tone === "correct"
                      ? "Как закрепить"
                      : "Как лучше ответить"}
                  </span>
                  <p>{item.improved_reply}</p>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="turn-review-empty">
          В этой попытке нет самостоятельных реплик. Готовые предложения не
          засчитываются как ваши ответы.
        </div>
      )}

      {summary && (
        <footer className="turn-review-footer">
          {summary.improvements.length > 0 && (
            <div>
              <strong>Ошибки и замечания из этой попытки</strong>
              <ul>
                {summary.improvements.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
          <p>
            <strong>Следующая тренировка:</strong> {summary.next_training}
          </p>
          <p className="turn-review-method">
            Проверка сделана по правилам деловой переписки. Если формулировка
            неоднозначна, отчёт отмечает нехватку контекста вместо догадки.
          </p>
        </footer>
      )}
    </section>
  );
}
