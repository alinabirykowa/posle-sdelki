import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Clock3,
  FileText,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  Target,
} from "lucide-react";
import { workspaceApi, type Account, type PublicCase } from "../workspace-api";
import { errorMessage } from "../api";
import {
  readPendingCatalogStart,
  getPendingCatalogStart,
  clearPendingCatalogStart,
  type PendingCatalogStart,
} from "../recovery";
import type { ReplyMode, Session, TrainingPreview } from "../types";
import { Modal, money } from "./UI";
import "../catalog-workspace.css";

type CaseDetail = { item: PublicCase; preview: TrainingPreview };
const INDUSTRIES = {
  digital: "Digital-услуги",
  it: "IT и автоматизация",
  consulting: "Консалтинг",
};

export function CatalogPage({
  user,
  liveAvailable,
  liveReplyMode,
  onStart,
  onLogin,
  refreshKey,
}: {
  user: Account | null;
  liveAvailable: boolean;
  liveReplyMode: ReplyMode;
  onStart: (session: Session) => void;
  onLogin: () => void;
  refreshKey: number;
}) {
  const [items, setItems] = useState<PublicCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [stale, setStale] = useState(false);
  const [mode, setMode] = useState<"demo" | "live">("demo");
  const [starting, setStarting] = useState(false);
  const [pendingStart, setPendingStart] = useState<PendingCatalogStart | null>(
    () => (user ? readPendingCatalogStart(user.id) : null),
  );
  const [attemptError, setAttemptError] = useState("");
  const [discardAttempt, setDiscardAttempt] = useState(false);
  const currentAccount = useRef(user?.id ?? null);
  currentAccount.current = user?.id ?? null;
  const alive = useRef(true);
  const listSequence = useRef(0);
  const detailSequence = useRef(0);
  const startingRef = useRef(false);
  const title = useRef<HTMLHeadingElement>(null);
  const detailRef = useRef<CaseDetail | null>(null);
  detailRef.current = detail;

  async function refreshList(quiet = false) {
    const sequence = ++listSequence.current;
    if (!quiet) setLoading(true);
    try {
      const result = await workspaceApi.catalog();
      if (!alive.current || sequence !== listSequence.current) return;
      setItems(result.items);
      setListError("");
      const current = detailRef.current;
      if (
        current &&
        !result.items.some(
          (item) =>
            item.id === current.item.id &&
            item.revision === current.item.revision,
        )
      )
        setStale(true);
    } catch (cause) {
      if (alive.current && sequence === listSequence.current)
        setListError(errorMessage(cause));
    } finally {
      if (alive.current && sequence === listSequence.current) setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    void refreshList();
    const refreshVisible = () => {
      if (document.visibilityState === "visible") void refreshList(true);
    };
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    const timer = window.setInterval(refreshVisible, 30_000);
    return () => {
      alive.current = false;
      listSequence.current += 1;
      detailSequence.current += 1;
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
      window.clearInterval(timer);
    };
  }, [refreshKey]);
  useEffect(() => {
    if (!liveAvailable) setMode("demo");
  }, [liveAvailable]);
  useEffect(() => {
    if (!detailLoading) title.current?.focus();
  }, [openedId, detailLoading]);

  useEffect(() => {
    setPendingStart(user ? readPendingCatalogStart(user.id) : null);
    setAttemptError("");
    setDiscardAttempt(false);
  }, [user?.id]);

  async function openCase(id: string) {
    if (startingRef.current) return;
    const sequence = ++detailSequence.current;
    setOpenedId(id);
    setDetail(null);
    setDetailLoading(true);
    setDetailError("");
    setStale(false);
    try {
      const result = await workspaceApi.catalogCase(id);
      if (!alive.current || sequence !== detailSequence.current) return;
      setDetail(result);
    } catch (cause) {
      if (alive.current && sequence === detailSequence.current)
        setDetailError(errorMessage(cause));
    } finally {
      if (alive.current && sequence === detailSequence.current)
        setDetailLoading(false);
    }
  }
  function goBack() {
    if (startingRef.current) return;
    detailSequence.current += 1;
    setOpenedId(null);
    setDetail(null);
    setDetailError("");
    setDetailLoading(false);
    setStale(false);
    void refreshList(true);
  }
  async function runStart(attempt: PendingCatalogStart, recovering: boolean) {
    if (startingRef.current || !user || attempt.user_id !== user.id) return;
    startingRef.current = true;
    setStarting(true);
    setAttemptError("");
    try {
      const session = await workspaceApi.startCase(
        attempt.case_id,
        attempt.revision,
        attempt.mode,
        attempt.id,
      );
      clearPendingCatalogStart(attempt);
      if (alive.current && currentAccount.current === attempt.user_id) {
        setPendingStart(null);
        onStart(session);
      }
    } catch (cause) {
      if (!alive.current || currentAccount.current !== attempt.user_id) return;
      const status =
        typeof cause === "object" && cause !== null && "status" in cause
          ? cause.status
          : undefined;
      if (status === 404 || status === 409) {
        // A rejected replay must never fall through to creating another session.
        clearPendingCatalogStart(attempt);
        setPendingStart(null);
        if (detailRef.current?.item.id === attempt.case_id) setStale(true);
        setAttemptError(
          recovering
            ? "Не удалось восстановить разговор: ситуация изменилась или снята с публикации. Новый разговор не создан. Обновите бриф, если хотите начать заново."
            : "Ситуация изменилась или больше не опубликована. Обновите бриф перед началом разговора.",
        );
      } else {
        setPendingStart(attempt);
        setAttemptError(errorMessage(cause));
      }
    } finally {
      startingRef.current = false;
      if (alive.current) setStarting(false);
    }
  }
  async function start() {
    if (!detail || stale || startingRef.current) return;
    if (!user) {
      onLogin();
      return;
    }
    const existing = readPendingCatalogStart(user.id);
    if (existing) {
      setPendingStart(existing);
      return;
    }
    if (mode === "live" && !liveAvailable) return;
    const attempt = getPendingCatalogStart(
      user.id,
      detail.item.id,
      detail.item.revision,
      mode,
    );
    await runStart(attempt, false);
  }

  return (
    <div className="catalog-workspace">
      {pendingStart && user?.id === pendingStart.user_id && (
        <section
          className="catalog-recovery"
          aria-labelledby="catalog-recovery-title"
        >
          <div>
            <h2 id="catalog-recovery-title">
              Предыдущий запуск не подтверждён
            </h2>
            <p>
              Возможно, разговор уже создан. Восстановим его с прежними
              настройками, даже если ситуация обновилась или исчезла из
              каталога.
            </p>
            <span>
              Версия {pendingStart.revision} ·{" "}
              {pendingStart.mode === "live" ? "AI-режим" : "Демо-сценарий"}
            </span>
          </div>
          <div className="catalog-recovery-actions">
            <button
              type="button"
              className="button primary"
              onClick={() => void runStart(pendingStart, true)}
              disabled={starting}
            >
              {starting ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <RefreshCw size={16} />
              )}
              {starting ? "Восстанавливаем…" : "Восстановить разговор"}
            </button>
            <button
              type="button"
              className="catalog-recovery-dismiss"
              onClick={() => setDiscardAttempt(true)}
              disabled={starting}
            >
              Забыть эту попытку
            </button>
          </div>
        </section>
      )}
      {attemptError && (
        <div className="catalog-error" role="alert">
          <p>{attemptError}</p>
        </div>
      )}
      {!openedId ? (
        <>
          <header className="catalog-heading">
            <div>
              <p className="catalog-kicker">Ситуации команды</p>
              <h1 ref={title} tabIndex={-1}>
                Практика из вашей работы.
              </h1>
              <p>
                Выберите ситуацию, узнайте контекст и попробуйте договориться с
                клиентом.
              </p>
            </div>
            {user?.role === "admin" && (
              <a href="#/admin" className="catalog-manage">
                Управлять ситуациями
                <ArrowUpRight size={16} />
              </a>
            )}
          </header>
          {listError && (
            <div className="catalog-error" role="alert">
              <p>{listError}</p>
              <button
                type="button"
                onClick={() => void refreshList()}
                disabled={loading}
              >
                Повторить загрузку
              </button>
            </div>
          )}
          {loading ? (
            <div className="catalog-empty" role="status">
              <LoaderCircle size={26} className="spin" />
              <p>Загружаем ситуации…</p>
            </div>
          ) : items.length ? (
            <>
              <div className="catalog-list-label">
                <span>Выберите разговор</span>
                <span>{items.length.toString().padStart(2, "0")}</span>
              </div>
              <div className="catalog-grid">
                {items.map((item, index) => (
                  <button
                    key={item.id}
                    type="button"
                    className="catalog-card"
                    onClick={() => void openCase(item.id)}
                  >
                    <span className="catalog-card-top">
                      <span>
                        {INDUSTRIES[item.content.configuration.industry]}
                      </span>
                      <span className="catalog-card-number">
                        {(index + 1).toString().padStart(2, "0")}
                      </span>
                    </span>
                    <strong>{item.content.title}</strong>
                    <span className="catalog-card-description">
                      {item.content.description}
                    </span>
                    <span className="catalog-card-bottom">
                      <span>
                        <Clock3 size={13} />
                        {item.content.configuration.duration_minutes} мин
                      </span>
                      <span>
                        {item.content.configuration.format === "voice" ? (
                          <AudioLines size={13} />
                        ) : (
                          <MessageCircle size={13} />
                        )}
                        {item.content.configuration.format === "voice"
                          ? "Голос"
                          : "Переписка"}
                      </span>
                      <ArrowUpRight size={19} className="catalog-card-arrow" />
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : (
            !listError && (
              <div className="catalog-empty">
                <FileText size={32} />
                <h2>Ситуации скоро появятся</h2>
                <p>
                  Когда администратор опубликует тренировку, она автоматически
                  появится здесь.
                </p>
                {user?.role === "admin" ? (
                  <a className="button primary" href="#/admin">
                    Добавить ситуацию
                    <ArrowRight size={16} />
                  </a>
                ) : (
                  <a className="button secondary" href="#/">
                    Настроить свой разговор
                    <ArrowRight size={16} />
                  </a>
                )}
              </div>
            )
          )}
        </>
      ) : (
        <>
          <button
            type="button"
            className="catalog-back"
            onClick={goBack}
            disabled={starting}
          >
            <ArrowLeft size={16} />
            Все ситуации
          </button>
          {detailLoading ? (
            <div className="catalog-empty" role="status">
              <LoaderCircle size={26} className="spin" />
              <p>Открываем бриф…</p>
            </div>
          ) : detail ? (
            <>
              <header className="catalog-heading catalog-detail-heading">
                <div>
                  <p className="catalog-kicker">
                    {INDUSTRIES[detail.item.content.configuration.industry]} ·{" "}
                    {detail.item.content.configuration.difficulty === "hard"
                      ? "Высокая сложность"
                      : "Обычная сложность"}
                  </p>
                  <h1 ref={title} tabIndex={-1}>
                    {detail.item.content.title}
                  </h1>
                  <p>{detail.item.content.description}</p>
                </div>
              </header>
              <div className="catalog-detail-layout">
                <div className="catalog-brief">
                  <section>
                    <h2>Контекст</h2>
                    <p className="catalog-paragraph">
                      {detail.item.content.briefing}
                    </p>
                  </section>
                  <section className="catalog-objective">
                    <Target size={20} />
                    <div>
                      <h2>Ваша задача</h2>
                      <p className="catalog-paragraph">
                        {detail.item.content.objective}
                      </p>
                    </div>
                  </section>
                  {detail.preview.scenario.practice_model === "conversation" &&
                    detail.preview.scenario.constraints.length > 0 && (
                      <details className="catalog-brief-details">
                        <summary>Что учитывать в разговоре</summary>
                        <ul className="catalog-constraints">
                          {detail.preview.scenario.constraints.map(
                            (constraint) => (
                              <li key={constraint}>{constraint}</li>
                            ),
                          )}
                        </ul>
                      </details>
                    )}
                  {detail.preview.scenario.practice_model !== "conversation" &&
                    detail.preview.scenario.constraints.length > 0 && (
                      <section>
                        <h2>Как пройти разговор</h2>
                        <ul className="catalog-constraints">
                          {detail.preview.scenario.constraints
                            .slice(0, 3)
                            .map((constraint) => (
                              <li key={constraint}>{constraint}</li>
                            ))}
                        </ul>
                        {detail.preview.scenario.constraints.length > 3 && (
                          <details className="catalog-brief-details">
                            <summary>Дополнительные детали</summary>
                            <ul className="catalog-constraints">
                              {detail.preview.scenario.constraints
                                .slice(3)
                                .map((constraint) => (
                                  <li key={constraint}>{constraint}</li>
                                ))}
                            </ul>
                          </details>
                        )}
                      </section>
                    )}
                  {detail.preview.scenario.practice_model !== "conversation" &&
                    detail.preview.scenario.baseline && (
                      <details className="catalog-brief-details">
                        <summary>Условия сохранённого сценария</summary>
                        <dl className="catalog-terms">
                          <div>
                            <dt>Цена проекта</dt>
                            <dd>
                              {money(detail.preview.scenario.baseline.price)}
                            </dd>
                          </div>
                          <div>
                            <dt>Срок</dt>
                            <dd>
                              {detail.preview.scenario.baseline.deadline_days}{" "}
                              дней
                            </dd>
                          </div>
                          <div>
                            <dt>Объём</dt>
                            <dd>{detail.preview.scenario.baseline.hours} ч</dd>
                          </div>
                          <div>
                            <dt>Ресурс команды</dt>
                            <dd>
                              {detail.preview.scenario.baseline.daily_capacity}{" "}
                              ч/день
                            </dd>
                          </div>
                        </dl>
                        <p className="catalog-payment">
                          {detail.preview.scenario.baseline.payment}
                        </p>
                      </details>
                    )}
                </div>
                <aside className="catalog-launch">
                  <div className="catalog-client">
                    <span className="catalog-client-avatar" aria-hidden="true">
                      {detail.item.content.client_name.slice(0, 1)}
                    </span>
                    <div>
                      <strong>{detail.item.content.client_name}</strong>
                      <span>
                        {detail.preview.scenario.client_role} ·{" "}
                        {detail.item.content.company}
                      </span>
                    </div>
                  </div>
                  <blockquote>«{detail.item.content.opening}»</blockquote>
                  <div className="catalog-session-meta">
                    <span>
                      <Clock3 size={14} />
                      {detail.item.content.configuration.duration_minutes} мин
                    </span>
                    <span>
                      {detail.item.content.configuration.format === "voice" ? (
                        <AudioLines size={14} />
                      ) : (
                        <MessageCircle size={14} />
                      )}
                      {detail.item.content.configuration.format === "voice"
                        ? "Голос"
                        : "Переписка"}
                    </span>
                    {detail.item.content.configuration.response_seconds > 0 && (
                      <span>
                        На ответ —{" "}
                        {detail.item.content.configuration.response_seconds}{" "}
                        сек.
                      </span>
                    )}
                  </div>
                  <label className="catalog-mode-select">
                    <span>Режим собеседника</span>
                    <select
                      value={mode}
                      onChange={(event) =>
                        setMode(event.target.value === "live" ? "live" : "demo")
                      }
                      disabled={starting || Boolean(pendingStart)}
                    >
                      <option value="demo">Демо-сценарий</option>
                      {liveAvailable && (
                        <option value="live">
                          {liveReplyMode === "generated"
                            ? "AI-собеседник"
                            : "AI-анализ"}
                        </option>
                      )}
                    </select>
                  </label>
                  {mode === "demo" && (
                    <p className="catalog-ai-note">
                      Ответы по подготовленным правилам.
                    </p>
                  )}
                  {mode === "live" && (
                    <p className="catalog-ai-note">
                      История разговора и бриф передаются внешнему AI-сервису.
                      Не вводите конфиденциальные данные компании.
                    </p>
                  )}
                  {stale && (
                    <div className="catalog-stale" role="status">
                      <p>
                        Есть новая версия или ситуация снята с публикации.
                        Проверьте актуальный бриф.
                      </p>
                      <button
                        type="button"
                        onClick={() => void openCase(detail.item.id)}
                        disabled={starting}
                      >
                        <RefreshCw size={14} />
                        Обновить бриф
                      </button>
                    </div>
                  )}
                  {detailError && (
                    <p className="catalog-start-error" role="alert">
                      {detailError}
                    </p>
                  )}
                  <button
                    type="button"
                    className="button primary catalog-start"
                    onClick={() => void start()}
                    disabled={starting || stale || Boolean(pendingStart)}
                  >
                    {starting ? (
                      <LoaderCircle size={17} className="spin" />
                    ) : (
                      <ArrowRight size={17} />
                    )}
                    {starting
                      ? "Открываем разговор…"
                      : user
                        ? "Начать разговор"
                        : "Войти и начать"}
                  </button>
                  <p className="catalog-launch-note">
                    После разговора — разбор решений и следующий шаг для
                    практики.
                  </p>
                </aside>
              </div>
            </>
          ) : (
            <div className="catalog-empty">
              <FileText size={28} />
              <h1 ref={title} tabIndex={-1}>
                Ситуация недоступна
              </h1>
              <p role="alert">
                {detailError || "Возможно, администратор снял её с публикации."}
              </p>
              <button
                type="button"
                className="button secondary"
                onClick={() => void openCase(openedId)}
              >
                <RefreshCw size={15} />
                Проверить ещё раз
              </button>
            </div>
          )}
        </>
      )}
      {discardAttempt && pendingStart && (
        <Modal
          title="Забыть попытку запуска?"
          onClose={() => setDiscardAttempt(false)}
        >
          <p className="catalog-discard-copy">
            Если разговор уже создан, он останется в «Моих разговорах». Мы
            перестанем восстанавливать эту попытку. Новый разговор автоматически
            не запустится.
          </p>
          <div className="catalog-discard-actions">
            <button
              className="button secondary"
              type="button"
              onClick={() => setDiscardAttempt(false)}
            >
              Вернуться
            </button>
            <button
              className="button primary"
              type="button"
              onClick={() => {
                clearPendingCatalogStart(pendingStart);
                setPendingStart(null);
                setDiscardAttempt(false);
                setAttemptError("");
              }}
            >
              Забыть попытку
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
