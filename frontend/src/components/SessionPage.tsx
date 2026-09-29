import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  Flag,
  Info,
  LoaderCircle,
  MessageCircle,
  Mic,
  RotateCcw,
  Send,
  SlidersHorizontal,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { api, errorMessage } from "../api";
import { pendingActions, reconcilePendingActions } from "../recovery";
import type { MentorAction, MentorMode, Session, Terms } from "../types";
import { mentorApi } from "../mentor-api";
import { Loading, Modal, ModeBadge, money } from "./UI";
import { PracticePace, VoicePractice } from "./VoicePractice";
import { ConversationCoach } from "./ConversationCoach";
import { appendTranscript } from "../voice";
import { ROUTE_STAGE_GUIDANCE } from "../progress-api";
import "../session-design.css";

const ROUTE_STAGES = [
  "discover",
  "explain",
  "objection",
  "independent",
] as const;

export function SessionPage({
  id,
  onRefresh,
  onHelp,
  onComplete,
}: {
  id: string;
  onRefresh: () => Promise<void>;
  onHelp: () => void;
  onComplete: (session: Session) => void;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [coachBusy, setCoachBusy] = useState(false);
  const [reloadCount, setReloadCount] = useState(0);
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [draft, setDraft] = useState(() => {
    try {
      return sessionStorage.getItem(`draft:${id}`) || "";
    } catch {
      return "";
    }
  });
  const [offers, setOffers] = useState(false);
  const [exit, setExit] = useState(false);
  const [mobileTerms, setMobileTerms] = useState(false);
  const [confirmation, setConfirmation] = useState(false);
  const [formatOverride, setFormatOverride] = useState<"text" | "voice" | null>(
    null,
  );
  const [audioInterrupt, setAudioInterrupt] = useState(0);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const scroll = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const drawer = useRef<HTMLDialogElement>(null);
  function acceptSession(next: Session, announce = false) {
    setSession(next);
    const recovered = reconcilePendingActions(id, next.messages);
    if (recovered.message !== null) {
      setDraft((current) =>
        current.trim() === recovered.message ? "" : current,
      );
      if (announce)
        setRecoveryNotice(
          "Сообщение уже сохранено. Разговор восстановлен без повторной отправки.",
        );
    }
    if (recovered.proposal && announce) {
      setRecoveryNotice(
        "Предложение уже сохранено. Показан актуальный ответ клиента.",
      );
    }
  }
  useEffect(() => {
    const field = input.current;
    if (!field) return;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, 160)}px`;
  }, [draft, loading]);
  useEffect(() => {
    let alive = true;
    api
      .session(id)
      .then((s) => {
        if (!alive) return;
        acceptSession(s, true);
        setError("");
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id, reloadCount]);
  useEffect(() => {
    try {
      sessionStorage.setItem(`draft:${id}`, draft);
    } catch {
      /* Storage is optional. */
    }
  }, [draft, id]);
  useEffect(() => {
    const el = scroll.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session?.messages.length, busy]);
  useEffect(() => {
    if (!loading && session?.status === "completed") {
      onComplete(session);
    }
  }, [loading, session, onComplete]);
  useEffect(() => {
    if (
      session &&
      session.turns >=
        (session.turn_limit ??
          (session.max_turns ?? 30) + (session.extra_turns ?? 0))
    ) {
      setError((current) =>
        current.startsWith("Достигнут лимит в ") ? "" : current,
      );
    }
  }, [session]);
  useEffect(() => {
    if (!mobileTerms) return;
    const dialog = drawer.current;
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const oldOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = oldOverflow;
      if (previousFocus?.isConnected)
        previousFocus.focus({ preventScroll: true });
    };
  }, [mobileTerms]);

  async function mutate(action: () => Promise<Session>, after?: () => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setRecoveryNotice("");
    try {
      const next = await action();
      if (!mounted.current) return;
      acceptSession(next);
      after?.();
      void onRefresh();
    } catch (e) {
      if (mounted.current) setError(errorMessage(e));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function send(text = draft) {
    text = text.trim();
    if (
      !text ||
      text.length > 2000 ||
      inFlight.current ||
      (session &&
        session.turns >=
          (session.turn_limit ??
            (session.max_turns ?? 30) + (session.extra_turns ?? 0)))
    )
      return;
    const messageId = pendingActions.get(`pending-message:${id}`, text).id;
    void mutate(
      () => api.message(id, text, messageId),
      () => {
        pendingActions.clear(`pending-message:${id}`, messageId);
        try {
          sessionStorage.removeItem(`draft:${id}`);
        } catch {
          /* Storage is optional. */
        }
        setDraft("");
        input.current?.focus();
      },
    );
  }
  function propose(optionId: string) {
    if (inFlight.current) return;
    const action = pendingActions.get(`pending-proposal:${id}`, optionId);
    void mutate(
      () => api.propose(id, optionId, action.id),
      () => {
        pendingActions.clear(`pending-proposal:${id}`, action.id);
        setOffers(false);
      },
    );
  }
  function reloadSession() {
    if (inFlight.current) return;
    setLoading(true);
    setReloadCount((count) => count + 1);
  }
  function extendConversation() {
    if (inFlight.current || !session) return;
    const key = `pending-extend:${id}`;
    const action = pendingActions.get(
      key,
      String(
        session.turn_limit ??
          (session.max_turns ?? 30) + (session.extra_turns ?? 0),
      ),
    );
    void mutate(
      async () => (await api.extend(id, action.id)).session,
      () => {
        pendingActions.clear(key, action.id);
        setRecoveryNotice("Добавлены 4 хода. Переписка и черновик сохранены.");
      },
    );
  }
  async function requestAdvice(action: MentorAction, messageId?: string) {
    if (inFlight.current)
      throw new Error("Дождитесь завершения предыдущего действия.");
    inFlight.current = true;
    setBusy(true);
    setCoachBusy(true);
    const key = `pending-mentor:${id}:${action}`;
    const pending = pendingActions.get(
      key,
      JSON.stringify({
        action,
        messageId,
        context: session?.messages.at(-1)?.id,
      }),
    );
    try {
      const result = await mentorApi.advice(id, action, pending.id, messageId);
      acceptSession(result.session);
      pendingActions.clear(key, pending.id);
      return result.advice;
    } finally {
      inFlight.current = false;
      setBusy(false);
      setCoachBusy(false);
    }
  }
  async function changeMentorMode(mode: MentorMode) {
    if (inFlight.current)
      throw new Error("Дождитесь завершения предыдущего действия.");
    inFlight.current = true;
    setBusy(true);
    setCoachBusy(true);
    const key = `pending-mentor-mode:${id}`;
    const pending = pendingActions.get(key, mode);
    try {
      const result = await mentorApi.mode(id, mode, pending.id);
      acceptSession(result.session);
      pendingActions.clear(key, pending.id);
    } finally {
      inFlight.current = false;
      setBusy(false);
      setCoachBusy(false);
    }
  }
  if (loading) return <Loading label="Открываем переговорную…" />;
  if (!session)
    return (
      <div className="error-state">
        <h1>Разговор недоступен</h1>
        <p role="alert">{error}</p>
        <button className="button secondary" onClick={reloadSession}>
          <RotateCcw size={16} /> Попробовать загрузить снова
        </button>
        <a href="#/" className="button primary">
          К практике <ArrowRight size={18} />
        </a>
      </div>
    );
  if (session.status === "completed")
    return <Loading label="Открываем разбор в личном кабинете…" />;
  const scenario = session.scenario;
  const conversationPractice = scenario.practice_model === "conversation";
  const voiceMode =
    (formatOverride ?? session.training_config?.format ?? "text") === "voice";
  const latestClientMessage = [...session.messages]
    .reverse()
    .find((message) => message.role === "assistant");
  const turnLimit =
    session.turn_limit ??
    (session.max_turns ?? 30) + (session.extra_turns ?? 0);
  const atLimit = session.turns >= turnLimit;
  const audioBlocked =
    busy || atLimit || offers || exit || mobileTerms || confirmation;
  const proposal = session.proposal;
  const terms = proposal?.terms || scenario.baseline;
  const initials = scenario.client_name
    .split(" ")
    .map((x) => x[0])
    .slice(0, 2)
    .join("");
  const renderTermsPanel = () => (
    <aside className="terms-panel mobile-open" aria-label="Детали разговора">
      <div className="terms-header">
        <div>
          <span className="eyebrow subtle">ДОГОВОРЁННОСТЬ</span>
          <h2>
            {conversationPractice ? "Детали разговора" : "Условия проекта"}
          </h2>
        </div>
        <button
          className="icon-button mobile-close"
          onClick={() => setMobileTerms(false)}
          aria-label="Закрыть условия"
        >
          <X size={20} />
        </button>
      </div>
      <span className={`terms-state ${proposal ? proposal.client_status : ""}`}>
        {!proposal ? (
          "Пока обсуждаем"
        ) : proposal.client_status === "accepted" ? (
          <>
            <Check size={13} />
            Клиент согласен · ждём вас
          </>
        ) : (
          <>
            <X size={13} />
            Предложение не принято
          </>
        )}
      </span>
      {terms ? (
        <>
          <TermsSummary terms={terms} baseline={scenario.baseline} />
          <div className="scope-copy">
            <span>СОСТАВ РАБОТ</span>
            <p>{terms.scope}</p>
          </div>
        </>
      ) : (
        <div className="scope-copy">
          <span>ВАША ЦЕЛЬ</span>
          <p>{scenario.objective}</p>
        </div>
      )}
      {proposal && (
        <div className={`proposal-reason ${proposal.client_status}`}>
          <strong>{proposal.label}</strong>
          {proposal.description && <p>{proposal.description}</p>}
          <p>{proposal.reason}</p>
        </div>
      )}
      {session.discovered_interests.length > 0 && (
        <div className="discovered">
          <span>
            <SparkleIcon />
            ВЫ УЗНАЛИ
          </span>
          {session.discovered_interests.map((interest) => (
            <p key={interest}>{interest}</p>
          ))}
        </div>
      )}
      <button
        className="button secondary full"
        onClick={() => {
          setOffers(true);
          setMobileTerms(false);
        }}
        disabled={busy || atLimit}
      >
        <SlidersHorizontal size={16} />
        {proposal ? "Обсудить другой вариант" : "Предложить решение"}
        <ArrowRight size={17} />
      </button>
      {proposal?.client_status === "accepted" && (
        <button
          className="button primary full finalize-button"
          disabled={busy}
          onClick={() => {
            setConfirmation(true);
            setMobileTerms(false);
          }}
        >
          Подтвердить договорённость
          <Check size={17} />
        </button>
      )}
      <p className="terms-hint">
        <Info size={14} />
        {conversationPractice
          ? "В разборе посмотрим, как вы выяснили интересы и обосновали своё предложение."
          : "Согласие клиента ещё не гарантирует, что проект получится выполнить. Проверим это в разборе."}
      </p>
    </aside>
  );

  return (
    <div className="session-page page-enter">
      <div className="session-nav">
        <a href="#/" className="back-link">
          <ArrowLeft size={16} />К практике
        </a>
        <span className="saved-label">
          <CheckCheck size={15} /> Попытка сохраняется
        </span>
      </div>
      <div className="session-heading">
        <div>
          <h1>{scenario.title}</h1>
          {session.route_stage && (
            <div className="session-route-goal">
              <span className="session-route-step">
                Этап {ROUTE_STAGES.indexOf(session.route_stage) + 1} из{" "}
                {ROUTE_STAGES.length}
              </span>
              <strong>
                Миссия · {ROUTE_STAGE_GUIDANCE[session.route_stage].title}
              </strong>
              <p>{ROUTE_STAGE_GUIDANCE[session.route_stage].goal}</p>
              <span className="session-route-reward">
                Отметка появится в маршруте, если приём подтвердится в вашей
                реплике.
              </span>
            </div>
          )}
        </div>
        <button
          className="text-button session-exit"
          onClick={() =>
            proposal?.client_status === "accepted"
              ? setConfirmation(true)
              : setExit(true)
          }
          disabled={busy}
        >
          <Flag size={16} />
          Завершить и посмотреть разбор
        </button>
      </div>
      <div className="room-meta">
        {session.training_config && (
          <PracticePace
            durationMinutes={session.training_config.duration_minutes}
            responseSeconds={session.training_config.response_seconds}
            messageId={latestClientMessage?.id}
            turns={session.turns}
            maxTurns={turnLimit}
            disabled={audioBlocked}
          />
        )}
      </div>
      {!conversationPractice && (
        <p className="legacy-practice-note">
          Это сохранённая попытка с прежними учебными расчётами. Новые
          тренировки посвящены самому разговору. <a href="#/">Начать новую</a>
        </p>
      )}
      {conversationPractice && (
        <p className="room-goal">
          <Target size={18} aria-hidden="true" />
          <span>
            <strong>Ваша цель</strong>
            {scenario.objective}
          </span>
        </p>
      )}
      <details className="brief-banner">
        <summary>
          <Target size={19} />
          <span>
            <strong>
              {conversationPractice
                ? "Контекст и правила ситуации"
                : "Задача и контекст"}
            </strong>
          </span>
          <ChevronDown size={18} />
        </summary>
        <div>
          {!conversationPractice && (
            <p className="brief-objective">{scenario.objective}</p>
          )}
          <p>{scenario.briefing}</p>
          <ul>
            {scenario.constraints.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      </details>
      <div
        className={`room-agreement${conversationPractice ? " conversation-agreement" : ""}`}
        aria-label="Договорённость"
      >
        <div className="room-agreement-status">
          <ClipboardCheck size={17} aria-hidden="true" />
          <span className={proposal?.client_status || ""}>
            {!proposal
              ? "Обсудите интересы и предложите решение"
              : proposal.client_status === "accepted"
                ? "Клиент согласен · подтвердите условия"
                : "Предложение не принято"}
          </span>
        </div>
        {terms && (
          <dl className="room-agreement-numbers">
            <div>
              <dt>Бюджет</dt>
              <dd>{money(terms.price)}</dd>
            </div>
            <div>
              <dt>Объём</dt>
              <dd>{terms.hours} ч</dd>
            </div>
            <div>
              <dt>Срок</dt>
              <dd>{terms.deadline_days} дн</dd>
            </div>
          </dl>
        )}
        {conversationPractice && (
          <button
            className="room-terms-button"
            onClick={() => setOffers(true)}
            disabled={busy || atLimit}
          >
            {proposal ? "Другой вариант" : "Предложить решение"}{" "}
            <ArrowRight size={16} />
          </button>
        )}
        {conversationPractice && proposal?.client_status === "accepted" ? (
          <button
            className="button primary"
            disabled={busy}
            onClick={() => setConfirmation(true)}
          >
            Подвести итог <Check size={16} />
          </button>
        ) : (
          (!conversationPractice ||
            proposal ||
            session.discovered_interests.length > 0) && (
            <button
              className="room-terms-button"
              onClick={() => setMobileTerms(true)}
              aria-haspopup="dialog"
              aria-expanded={mobileTerms}
            >
              {conversationPractice ? "Что обсудили" : "Условия проекта"}{" "}
              <ArrowRight size={16} />
            </button>
          )
        )}
      </div>
      {recoveryNotice && (
        <p className="recovery-notice" role="status">
          {recoveryNotice}
        </p>
      )}
      <div className="negotiation-grid">
        <section className="conversation" aria-label="Разговор с клиентом">
          <header className="conversation-header">
            <div className="client-avatar" aria-hidden="true">
              {initials}
            </div>
            <div className="client-info">
              <strong>{scenario.client_name}</strong>
              <span>
                {scenario.client_role} · {scenario.company}
              </span>
            </div>
            <ModeBadge
              mode={session.mode}
              replyMode={session.reply_mode}
              onClick={() => {
                setAudioInterrupt((current) => current + 1);
                onHelp();
              }}
            />
          </header>
          <div
            className="conversation-format"
            role="group"
            aria-label="Формат ответа"
          >
            <button
              aria-pressed={!voiceMode}
              onClick={() => setFormatOverride("text")}
              disabled={busy}
            >
              <MessageCircle size={15} />
              Переписка
            </button>
            <button
              aria-pressed={voiceMode}
              onClick={() => setFormatOverride("voice")}
              disabled={busy}
            >
              <Mic size={15} />
              Голосовая практика
            </button>
            <span>Один разговор · любой формат</span>
          </div>
          <div hidden={!voiceMode}>
            <VoicePractice
              clientName={scenario.client_name}
              message={latestClientMessage}
              disabled={audioBlocked || !voiceMode}
              interruptKey={audioInterrupt}
              draft={draft}
              onUseTranscript={(transcript) => {
                const next = appendTranscript(draftRef.current, transcript);
                if (next === null) return false;
                setDraft(next);
                input.current?.focus();
                return true;
              }}
              onTextMode={() => setFormatOverride("text")}
            />
          </div>
          <div
            className="conversation-messages"
            ref={scroll}
            role="log"
            aria-label="Сообщения"
            aria-live="polite"
          >
            <div className="conversation-start">
              <span />
              НАЧАЛО РАЗГОВОРА
              <span />
            </div>
            {session.messages.map((message) => (
              <div className={`message ${message.role}`} key={message.id}>
                {message.role !== "system" && (
                  <span className="message-author">
                    {message.role === "user"
                      ? "Вы"
                      : scenario.client_name.split(" ")[0]}
                  </span>
                )}
                <div
                  className={`bubble ${message.kind === "proposal" ? "offer-bubble" : ""}`}
                >
                  {message.kind === "proposal" && <ClipboardCheck size={16} />}
                  <span>{message.text}</span>
                </div>
              </div>
            ))}
            {busy && !coachBusy && (
              <div className="typing" role="status">
                <span />
                <span />
                <span />
                <small>Готовим ответ…</small>
              </div>
            )}
          </div>
          <div className="conversation-input">
            {atLimit && (
              <section
                className="room-limit"
                aria-labelledby="room-limit-title"
              >
                <div>
                  <h2 id="room-limit-title">Запланированные ходы пройдены</h2>
                  <p>
                    Вы использовали {turnLimit} ходов. Откройте разбор в личном
                    кабинете или продолжите ещё на четыре хода.
                  </p>
                </div>
                <div className="room-limit-actions">
                  <button
                    type="button"
                    className="button primary"
                    disabled={busy}
                    onClick={() =>
                      proposal?.client_status === "accepted"
                        ? setConfirmation(true)
                        : setExit(true)
                    }
                  >
                    Завершить и посмотреть разбор <ArrowRight size={16} />
                  </button>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={busy}
                    onClick={extendConversation}
                  >
                    Продолжить разговор (+4 хода)
                  </button>
                </div>
              </section>
            )}
            <div className="composer-heading">
              <label htmlFor="message-input">Ваша реплика</label>
              <span>Здесь можно говорить своими словами</span>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
            >
              <textarea
                id="message-input"
                ref={input}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                maxLength={2000}
                rows={2}
                placeholder="С чего начнём? Напишите вопрос или свой вариант…"
                disabled={busy || atLimit}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <button
                className="send-button"
                disabled={busy || atLimit || !draft.trim()}
                aria-label={
                  voiceMode ? "Отправить ответ" : "Отправить сообщение"
                }
              >
                {busy ? (
                  <LoaderCircle size={19} className="spin" />
                ) : (
                  <Send size={19} />
                )}
              </button>
            </form>
            <div className="input-caption">
              <span>Enter — отправить · Shift + Enter — новая строка</span>
              <span>{draft.length > 1600 ? `${draft.length}/2000` : ""}</span>
            </div>
            <ConversationCoach
              session={session}
              busy={busy || atLimit}
              onAdvice={requestAdvice}
              onMode={changeMentorMode}
              onAdd={(text) => {
                if (draftRef.current.includes(text.trim())) {
                  input.current?.focus();
                  return "existing";
                }
                const next = appendTranscript(draftRef.current, text);
                if (next === null) return "limit";
                draftRef.current = next;
                setDraft(next);
                input.current?.focus();
                return "added";
              }}
            />
          </div>
        </section>
      </div>
      {error && (
        <div className="inline-error session-error" role="alert">
          <span>{error}</span>
          <button
            className="text-button"
            onClick={reloadSession}
            disabled={busy}
          >
            Обновить попытку
          </button>
          <button
            className="icon-button"
            onClick={() => setError("")}
            aria-label="Закрыть уведомление"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {mobileTerms && (
        <dialog
          ref={drawer}
          className="terms-drawer"
          aria-label="Детали разговора"
          onCancel={(event) => {
            event.preventDefault();
            setMobileTerms(false);
          }}
          onClick={(event) => {
            if (event.target === drawer.current) setMobileTerms(false);
          }}
        >
          {renderTermsPanel()}
        </dialog>
      )}
      {offers && (
        <Modal
          title="Какой вариант предложим?"
          onClose={busy ? () => {} : () => setOffers(false)}
          wide
        >
          <p className="modal-description">
            Выберите вариант для обсуждения. Собеседник ответит, подходит ли он
            под его приоритеты. После согласия вы сможете подвести итог.
          </p>
          <div className="offer-grid negotiation-offers">
            {scenario.options.map((option) => (
              <button
                className="offer-option"
                disabled={busy || atLimit}
                key={option.id}
                onClick={() => propose(option.id)}
              >
                <div className="offer-option-title">
                  <h3>{option.label}</h3>
                  <ArrowUpRightIcon />
                </div>
                <p>{option.description}</p>
                {option.terms && (
                  <div className="offer-numbers">
                    <span>
                      <b>{money(option.terms.price)}</b>цена
                    </span>
                    <span>
                      <b>{option.terms.hours} ч</b>объём
                    </span>
                    <span>
                      <b>{option.terms.deadline_days} дн.</b>срок
                    </span>
                  </div>
                )}
                <div className="offer-action">
                  {busy ? "Обсуждаем…" : "Предложить клиенту"}
                  <ArrowRight size={15} />
                </div>
              </button>
            ))}
          </div>
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
        </Modal>
      )}
      {confirmation && (
        <Modal
          title="Подтверждаем договорённость?"
          onClose={busy ? () => {} : () => setConfirmation(false)}
        >
          <p className="modal-description">
            Собеседник согласен с решением «{proposal?.label}». Завершите
            разговор — откроется личный кабинет с разбором и рекомендациями.
          </p>
          {draft.trim() && (
            <p className="modal-description">
              В поле ответа остался черновик. В разбор войдут только
              отправленные реплики. Вернитесь к разговору, если хотите сначала
              отправить этот текст.
            </p>
          )}
          {terms ? (
            <TermsSummary terms={terms} />
          ) : (
            <p className="agreement-description">
              {proposal?.description || proposal?.reason}
            </p>
          )}
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setConfirmation(false)}
            >
              Ещё обсудить
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() =>
                void mutate(
                  () => api.finish(id, "agreement"),
                  () => setConfirmation(false),
                )
              }
            >
              {busy ? "Готовим разбор…" : "Подтвердить и открыть разбор"}
              <ArrowRight size={17} />
            </button>
          </div>
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
        </Modal>
      )}
      {exit && (
        <Modal
          title="Открыть разбор разговора?"
          onClose={busy ? () => {} : () => setExit(false)}
        >
          <div className="exit-icon">
            <Flag size={30} />
          </div>
          <p className="modal-description">
            Сохраним переписку и откроем разбор в личном кабинете. Итоговые
            условия пока не подтверждены — это результат разговора, а не ошибка.
            В разборе посмотрим, что получилось и что потренировать.
          </p>
          {draft.trim() && (
            <p className="modal-description">
              В поле ответа остался черновик. В разбор войдут только
              отправленные реплики. Вернитесь к разговору, если хотите сначала
              отправить этот текст.
            </p>
          )}
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setExit(false)}
            >
              Вернуться к разговору
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() =>
                void mutate(
                  () => api.finish(id, "no_agreement"),
                  () => setExit(false),
                )
              }
            >
              {busy ? "Готовим разбор…" : "Завершить и открыть разбор"}
              <ArrowRight size={17} />
            </button>
          </div>
          {error && (
            <p role="alert" className="inline-error">
              {error}
            </p>
          )}
        </Modal>
      )}
      <div className="session-bottom-note">
        <CircleHelp size={14} />
        <span>
          В этой ситуации нет одной правильной фразы. Ищите условия, которые
          подходят обеим сторонам.
        </span>
        <RotateCcw size={14} />
        <span>Повтор доступен после разбора.</span>
      </div>
    </div>
  );
}

export function TermsSummary({
  terms,
  baseline,
}: {
  terms: Terms;
  baseline?: Terms | null;
}) {
  return (
    <div className="terms-summary">
      <div>
        <span>Стоимость</span>
        <strong>
          {money(terms.price)}
          {baseline && terms.price !== baseline.price && (
            <small>было {money(baseline.price)}</small>
          )}
        </strong>
      </div>
      <div>
        <span>Объём работы</span>
        <strong>
          {terms.hours} часов
          {baseline && terms.hours !== baseline.hours && (
            <small>было {baseline.hours} часов</small>
          )}
        </strong>
      </div>
      <div>
        <span>Срок</span>
        <strong>{terms.deadline_days} раб. дней</strong>
      </div>
      <div>
        <span>Оплата</span>
        <strong className="payment-term">{terms.payment}</strong>
      </div>
    </div>
  );
}

function SparkleIcon() {
  return <Sparkles size={18} className="sparkle-tiny" aria-hidden="true" />;
}
function ArrowUpRightIcon() {
  return <ArrowRight size={20} className="rotate-arrow" />;
}
