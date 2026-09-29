import { useEffect, useRef, useState } from "react";
import {
  Award,
  Check,
  ChevronDown,
  Compass,
  LoaderCircle,
  Target,
} from "lucide-react";
import { errorMessage } from "../api";
import {
  progressApi,
  type AssistanceKind,
  type NegotiatorRoute,
  type PracticeProgress,
  type ProgressEvidence,
  type ProgressSkill,
  type RouteStageId,
  type SkillStatus,
} from "../progress-api";
import { plural } from "./UI";
import { SavedSessionReview } from "./SavedSessionReview";
import "../progress-design.css";

const ASSISTANCE: Record<AssistanceKind, string> = {
  guided: "Режим с помощником",
  independent: "Самостоятельно",
  unknown: "Нет данных о помощи",
};
const STATUS: Record<SkillStatus, string> = {
  observed: "Замечен в репликах",
  not_observed: "Пока не отмечен",
  not_practiced: "Нет наблюдений",
};
const shortDate = (iso: string | null) => {
  if (!iso) return "Дата не указана";
  const value = new Date(iso);
  return Number.isNaN(value.getTime())
    ? "Дата не указана"
    : new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }).format(value);
};
const year = (iso: string | null) => {
  if (!iso) return "";
  const value = new Date(iso);
  return Number.isNaN(value.getTime()) ? "" : String(value.getFullYear());
};
function skillDescription(skill: ProgressSkill) {
  if (skill.status === "not_practiced" || skill.eligible_count === 0)
    return skill.not_practiced_count > 0
      ? "В завершённых попытках пока недостаточно данных для наблюдения за этим приёмом."
      : "Наблюдение появится после завершённого разговора.";
  if (skill.status === "not_observed")
    return `В ${skill.eligible_count} ${plural(skill.eligible_count, ["учтённом разговоре", "учтённых разговорах", "учтённых разговорах"])} этот приём пока не отмечен.`;
  return `Приём отмечен в ${skill.observed_count} из ${skill.eligible_count} ${plural(skill.eligible_count, ["учтённого разговора", "учтённых разговоров", "учтённых разговоров"])}. Ниже — реплики, на которых основано наблюдение.`;
}

function NegotiatorRouteView({
  route,
  busy,
  onPractice,
  onReview,
}: {
  route: NegotiatorRoute;
  busy: boolean;
  onPractice: (stage: RouteStageId | null) => void;
  onReview: (sessionId: string) => void;
}) {
  const active = route.stages.find((stage) => stage.status === "available");
  const completion = route.total_stages
    ? Math.round((route.completed_stages / route.total_stages) * 100)
    : 0;
  return (
    <section
      className="negotiator-route"
      aria-labelledby="negotiator-route-title"
    >
      <header className="negotiator-route-heading">
        <div>
          <span className="negotiator-route-eyebrow">Маршрут практики</span>
          <h2 id="negotiator-route-title">{route.title}</h2>
          <p>
            Проходите задания по очереди. Этап засчитывается, когда приём
            подтверждён репликой в завершённом разговоре.
          </p>
        </div>
        <div className="negotiator-route-score" aria-label="Прогресс маршрута">
          <strong>{route.completed_stages}</strong>
          <span>из {route.total_stages} этапов</span>
        </div>
      </header>
      <div
        className="negotiator-route-progress"
        role="progressbar"
        aria-label="Этапы маршрута пройдены"
        aria-valuemin={0}
        aria-valuemax={route.total_stages}
        aria-valuenow={route.completed_stages}
      >
        <span style={{ width: `${completion}%` }} />
      </div>
      <aside className="route-mentor">
        <span className="route-mentor-avatar" aria-hidden="true">
          <Compass size={19} />
        </span>
        <div>
          <span className="route-mentor-name">Подсказка наставника</span>
          <p>
            {active
              ? active.challenge
              : "Все этапы маршрута подтверждены вашими репликами. Выберите новую ситуацию и проверьте навыки в другом разговоре."}
          </p>
        </div>
      </aside>
      <ol className="negotiator-route-stages">
        {route.stages.map((stage, index) => (
          <li
            className={`route-stage route-${stage.status}`}
            key={stage.id}
            aria-current={stage.status === "available" ? "step" : undefined}
          >
            <span className="route-stage-marker" aria-hidden="true">
              {stage.status === "complete" ? (
                <Check size={15} />
              ) : stage.status === "locked" ? (
                <span>{String(index + 1)}</span>
              ) : (
                <Target size={15} />
              )}
            </span>
            <div className="route-stage-content">
              <div className="route-stage-title-row">
                <h3>{stage.title}</h3>
                <span>
                  {stage.status === "complete"
                    ? "Отметка получена"
                    : stage.status === "available"
                      ? "Текущий этап"
                      : "Закрыт"}
                </span>
              </div>
              <p>{stage.challenge}</p>
              {stage.evidence.map((evidence) => (
                <figure
                  className="route-stage-evidence"
                  key={`${stage.id}:${evidence.session_id}`}
                >
                  <blockquote>«{evidence.quote}»</blockquote>
                  <figcaption>
                    Подтверждение из «{evidence.title}»
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onReview(evidence.session_id)}
                    >
                      Открыть разбор
                    </button>
                  </figcaption>
                </figure>
              ))}
            </div>
          </li>
        ))}
      </ol>
      <div className="negotiator-route-footer">
        <p>
          <Award size={16} aria-hidden="true" />
          {route.rule}
        </p>
        <button
          type="button"
          className="button primary"
          disabled={
            busy || (!active && route.completed_stages < route.total_stages)
          }
          onClick={() => onPractice(active?.id ?? null)}
        >
          {active
            ? `Тренировать этап: ${active.title}`
            : route.completed_stages === route.total_stages
              ? "Продолжить практику"
              : "Завершите текущий этап"}
        </button>
      </div>
    </section>
  );
}

export function ProgressPage({
  authenticated,
  identityKey,
  onOpen,
  onPractice,
  onRoutePractice,
  onRetry,
  onReview,
  reviewId,
}: {
  authenticated: boolean;
  identityKey: string;
  onOpen: (sessionId: string) => void | Promise<void>;
  onPractice: () => void | Promise<void>;
  onRoutePractice: (stage: RouteStageId | null) => void | Promise<void>;
  onRetry: (sessionId: string) => void | Promise<void>;
  onReview: (sessionId: string) => void;
  reviewId?: string;
}) {
  const [saved, setSaved] = useState<{
    owner: string;
    data: PracticeProgress;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const mounted = useRef(true);
  const requestSequence = useRef(0);
  const busyRef = useRef(false);
  const currentOwner = useRef(identityKey);
  currentOwner.current = identityKey;
  const data = saved?.owner === identityKey ? saved.data : null;

  async function refresh(owner: string) {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await progressApi.get();
      if (
        mounted.current &&
        currentOwner.current === owner &&
        sequence === requestSequence.current
      )
        setSaved({ owner, data: result });
    } catch (cause) {
      if (
        mounted.current &&
        currentOwner.current === owner &&
        sequence === requestSequence.current
      )
        setError(errorMessage(cause));
    } finally {
      if (
        mounted.current &&
        currentOwner.current === owner &&
        sequence === requestSequence.current
      )
        setLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    setSaved(null);
    setActionError("");
    setBusy(null);
    busyRef.current = false;
    void refresh(identityKey);
    const onFocus = () => {
      if (document.visibilityState === "visible") void refresh(identityKey);
    };
    window.addEventListener("focus", onFocus);
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
      window.removeEventListener("focus", onFocus);
    };
  }, [identityKey]);

  async function act(key: string, action: () => void | Promise<void>) {
    if (busyRef.current) return;
    const owner = identityKey;
    busyRef.current = true;
    setBusy(key);
    setActionError("");
    try {
      await action();
    } catch (cause) {
      if (mounted.current && currentOwner.current === owner)
        setActionError(errorMessage(cause));
    } finally {
      if (currentOwner.current === owner) {
        busyRef.current = false;
        if (mounted.current) setBusy(null);
      }
    }
  }
  function nextPractice() {
    if (!data) return;
    const recommendation = data.recommendation;
    if (recommendation.kind === "continue" && recommendation.session_id) {
      void act("next", () => onOpen(recommendation.session_id!));
    } else if (recommendation.kind === "retry" && recommendation.session_id) {
      void act("next", () => onRetry(recommendation.session_id!));
    } else void act("next", onPractice);
  }
  function evidenceFigure(evidence: ProgressEvidence) {
    const sourceDate = evidence.completed_at || evidence.created_at;
    return (
      <figure
        className="progress-evidence"
        key={`${evidence.session_id}:${evidence.message_id}`}
      >
        <blockquote>«{evidence.quote}»</blockquote>
        <figcaption>
          <span>{ASSISTANCE[evidence.assistance]}</span>
          <time dateTime={sourceDate || undefined}>
            {shortDate(sourceDate)}
          </time>
          <button
            type="button"
            onClick={() =>
              void act(evidence.session_id, () => onReview(evidence.session_id))
            }
            disabled={Boolean(busy)}
            aria-label={`Открыть разговор: ${evidence.title}`}
          >
            Открыть разговор
          </button>
        </figcaption>
      </figure>
    );
  }

  const recent =
    data?.recent_practice.filter(
      (entry) => entry.practice_model === "conversation",
    ) || [];
  const comparison = data?.comparison;
  const hasComparison =
    comparison?.eligible && comparison.previous && comparison.current;
  const conversationCount = data?.summary.conversation_completed || 0;
  const selectedReview = reviewId ?? data?.latest_completed?.session_id;
  const activeConversationId =
    data?.recommendation.kind === "continue"
      ? data.recommendation.session_id
      : null;
  const activeConversation = recent.find(
    (entry) => entry.session_id === activeConversationId,
  );
  const reviewingActiveConversation = Boolean(
    activeConversationId && selectedReview === activeConversationId,
  );
  return (
    <div className="progress-page">
      <header className="progress-heading">
        <div>
          <h1>Личный кабинет</h1>
          <p>
            Ваши разговоры, наблюдения по навыкам и следующий шаг в практике.
          </p>
        </div>
        <a href="#/history">Мои разговоры</a>
      </header>
      {!authenticated && (
        <p className="progress-guest-note">
          Здесь — практика из этого браузера. <a href="#/login">Войдите</a>,
          чтобы открыть историю аккаунта. Гостевые разговоры автоматически в неё
          не переносятся.
        </p>
      )}
      {activeConversationId && !reviewingActiveConversation && (
        <section
          className="progress-resume"
          aria-labelledby="progress-resume-title"
        >
          <div>
            <h2 id="progress-resume-title">Незавершённый разговор</h2>
            <p>
              {activeConversation?.title ||
                "Переписка сохранена в вашем кабинете."}
            </p>
          </div>
          <div className="progress-resume-actions">
            <button
              type="button"
              className="button secondary"
              disabled={Boolean(busy)}
              onClick={() =>
                void act("continue", () => onOpen(activeConversationId))
              }
            >
              {busy === "continue" ? "Открываем…" : "Продолжить"}
            </button>
            <button
              type="button"
              className="progress-new-conversation"
              disabled={Boolean(busy)}
              onClick={() => void act("new", onPractice)}
            >
              Новый разговор
            </button>
          </div>
        </section>
      )}
      {selectedReview && (
        <SavedSessionReview
          key={`${identityKey}:${selectedReview}`}
          id={selectedReview}
          onRetry={onRetry}
          onPractice={() => {
            void onPractice();
          }}
          onContinue={(id) => {
            void onOpen(id);
          }}
        />
      )}
      {reviewingActiveConversation && (
        <button
          type="button"
          className="progress-new-conversation progress-after-active-review"
          disabled={Boolean(busy)}
          onClick={() => void act("new", onPractice)}
        >
          Новый разговор
        </button>
      )}
      {error && (
        <div className="progress-error" role="alert">
          <strong>Не получилось загрузить прогресс</strong>
          <p>{error}</p>
          {data && <p>Ниже — данные последней успешной загрузки.</p>}
          <button
            type="button"
            onClick={() => void refresh(identityKey)}
            disabled={loading}
          >
            Повторить загрузку
          </button>
        </div>
      )}
      {actionError && (
        <div className="progress-error" role="alert">
          <strong>Не получилось открыть разговор</strong>
          <p>{actionError}</p>
        </div>
      )}
      {!data && loading && (
        <div className="progress-loading" role="status">
          <LoaderCircle size={21} className="spin" />
          <span>Собираем вашу практику…</span>
        </div>
      )}
      {data && (
        <>
          {loading && (
            <p className="progress-refreshing" role="status">
              Обновляем прогресс…
            </p>
          )}
          <dl className="progress-facts" aria-label="Ваши разговоры">
            <div>
              <dt>завершено</dt>
              <dd>{data.summary.completed}</dd>
            </div>
            <div>
              <dt>в процессе</dt>
              <dd>{data.summary.active}</dd>
            </div>
          </dl>
          <NegotiatorRouteView
            route={data.negotiator_route}
            busy={Boolean(busy)}
            onPractice={(stage) =>
              void act("route", () => onRoutePractice(stage))
            }
            onReview={(sessionId) =>
              void act(sessionId, () => onReview(sessionId))
            }
          />
          {!selectedReview && !activeConversationId && (
            <section
              className="progress-next"
              aria-labelledby="progress-next-title"
            >
              <div>
                <h2 id="progress-next-title">
                  {data.summary.total === 0
                    ? "Первый разговор — точка отсчёта"
                    : data.recommendation.label}
                </h2>
                <p>{data.recommendation.reason}</p>
              </div>
              <button
                className="button primary"
                type="button"
                onClick={nextPractice}
                disabled={Boolean(busy)}
              >
                {busy === "next" && <LoaderCircle size={16} className="spin" />}
                {busy === "next"
                  ? "Открываем…"
                  : data.recommendation.kind === "continue"
                    ? "Продолжить разговор"
                    : "Следующая тренировка"}
              </button>
            </section>
          )}
          <section
            className="progress-section"
            aria-labelledby="progress-skills-title"
          >
            <div className="progress-section-heading">
              <h2 id="progress-skills-title">Навыки в разговорах</h2>
            </div>
            <p className="progress-scope">
              {data.observation_scope.title && (
                <strong>{data.observation_scope.title}</strong>
              )}
              {data.observation_scope.reason}
            </p>
            <div className="progress-skills">
              {data.skills.map((skill) => (
                <details className="progress-skill" key={skill.id}>
                  <summary>
                    <strong>{skill.label}</strong>
                    <span
                      className={`progress-skill-status ${skill.status === "observed" ? "is-observed" : ""}`}
                    >
                      {STATUS[skill.status]}
                    </span>
                    <ChevronDown
                      size={16}
                      className="progress-skill-marker"
                      aria-hidden="true"
                    />
                  </summary>
                  <div className="progress-skill-body">
                    <p>{skillDescription(skill)}</p>
                    {skill.evidence.map(evidenceFigure)}
                  </div>
                </details>
              ))}
            </div>
            {conversationCount > 0 && (
              <>
                <dl
                  className="progress-assistance"
                  aria-label="Помощь в завершённых разговорных тренировках"
                >
                  <div>
                    <dt>режим с помощником</dt>
                    <dd>{data.summary.assistance.guided}</dd>
                  </div>
                  <div>
                    <dt>самостоятельно</dt>
                    <dd>{data.summary.assistance.independent}</dd>
                  </div>
                  {data.summary.assistance.unknown > 0 && (
                    <div>
                      <dt>нет данных о помощи</dt>
                      <dd>{data.summary.assistance.unknown}</dd>
                    </div>
                  )}
                </dl>
                <p className="progress-assistance-note">
                  Учтены все завершённые разговорные тренировки. Если сведения о
                  помощи не сохранены, попытка не считается самостоятельной.
                </p>
              </>
            )}
            {hasComparison && comparison?.previous && comparison.current && (
              <details className="progress-comparison">
                <summary>
                  Сравнить две последние сопоставимые попытки
                  <ChevronDown size={16} aria-hidden="true" />
                </summary>
                <p>{comparison.reason}</p>
                <div className="progress-comparison-context">
                  <div>
                    <strong>Раньше</strong>
                    <span>
                      {shortDate(
                        comparison.previous.completed_at ||
                          comparison.previous.created_at,
                      )}
                    </span>
                    <span>
                      {comparison.previous.assistance === "guided" &&
                      comparison.previous.mentor_used === true
                        ? "Использованы подсказки"
                        : ASSISTANCE[comparison.previous.assistance]}
                    </span>
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        void act(comparison.previous!.session_id, () =>
                          onReview(comparison.previous!.session_id),
                        )
                      }
                    >
                      Открыть разговор
                    </button>
                  </div>
                  <div>
                    <strong>Сейчас</strong>
                    <span>
                      {shortDate(
                        comparison.current.completed_at ||
                          comparison.current.created_at,
                      )}
                    </span>
                    <span>
                      {comparison.current.assistance === "guided" &&
                      comparison.current.mentor_used === true
                        ? "Использованы подсказки"
                        : ASSISTANCE[comparison.current.assistance]}
                    </span>
                    <button
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() =>
                        void act(comparison.current!.session_id, () =>
                          onReview(comparison.current!.session_id),
                        )
                      }
                    >
                      Открыть разговор
                    </button>
                  </div>
                </div>
                <div className="progress-comparison-skills">
                  {comparison.current.skills.map((skill) => {
                    const earlier = comparison.previous!.skills.find(
                      (entry) => entry.id === skill.id,
                    );
                    const renderPoint = (
                      label: string,
                      point:
                        (typeof comparison.current.skills)[number] | undefined,
                    ) => {
                      const evidence = point?.evidence[0];
                      return (
                        <div className="progress-comparison-side" key={label}>
                          <small>{label}</small>
                          <strong>
                            {point ? STATUS[point.status] : "Нет наблюдений"}
                          </strong>
                          {evidence ? (
                            <>
                              <blockquote>«{evidence.quote}»</blockquote>
                              {evidence.delivery_label && (
                                <span className="comparison-delivery">
                                  {evidence.delivery_label}
                                </span>
                              )}
                              {evidence.client_reply && (
                                <p>
                                  <b>Реакция клиента:</b>{" "}
                                  {evidence.client_reply}
                                </p>
                              )}
                            </>
                          ) : (
                            <p>В этой попытке нет цитаты для этого навыка.</p>
                          )}
                        </div>
                      );
                    };
                    return (
                      <div className="progress-comparison-skill" key={skill.id}>
                        <strong>{skill.label}</strong>
                        <div className="progress-comparison-sides">
                          {renderPoint("Раньше", earlier)}
                          {renderPoint("Сейчас", skill)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </details>
            )}
          </section>
          <section
            className="progress-section"
            aria-labelledby="progress-recent-title"
          >
            <div className="progress-section-heading">
              <h2 id="progress-recent-title">Последние разговоры</h2>
              <a href="#/history" className="progress-history-link">
                Вся история
              </a>
            </div>
            {recent.length ? (
              <ol className="progress-timeline">
                {recent.map((entry) => {
                  const iso = entry.completed_at || entry.created_at;
                  return (
                    <li className="progress-entry" key={entry.session_id}>
                      <time
                        dateTime={iso || undefined}
                        aria-label={`${entry.completed_at ? "Завершён" : "Начат"} ${shortDate(iso)} ${year(iso)}`}
                      >
                        {shortDate(iso)}
                        <span>{year(iso)}</span>
                      </time>
                      <div>
                        <button
                          type="button"
                          className="progress-entry-title"
                          onClick={() =>
                            void act(entry.session_id, () =>
                              entry.status === "completed"
                                ? onReview(entry.session_id)
                                : onOpen(entry.session_id),
                            )
                          }
                          disabled={Boolean(busy)}
                        >
                          {entry.title}
                        </button>
                        <p className="progress-entry-info">
                          <span>
                            {entry.assistance === "guided" &&
                            entry.mentor_used === true
                              ? "Использованы подсказки"
                              : ASSISTANCE[entry.assistance]}
                          </span>
                          <span>
                            {entry.mode === "demo"
                              ? "Демо-сценарий"
                              : "AI-режим"}
                          </span>
                        </p>
                      </div>
                      <span
                        className={`progress-entry-status ${entry.status === "active" ? "is-active" : ""}`}
                      >
                        {entry.status === "active" ? "В процессе" : "Завершён"}
                      </span>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="progress-empty-note">
                Здесь появятся ваши разговорные тренировки. После завершения
                можно вернуться к репликам и разбору.
              </p>
            )}
            {data.summary.legacy_completed > 0 && (
              <p className="progress-legacy-note">
                Прежние сценарии с расчётом условий сохранены в{" "}
                <a href="#/history">истории</a>. Они не входят в наблюдения по
                навыкам этого кабинета.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
