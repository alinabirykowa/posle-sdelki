import { useEffect, useState } from "react";
import {
  ArrowUpLeft,
  ChevronDown,
  Lightbulb,
  LoaderCircle,
  MessageCircle,
  PencilLine,
  Search,
} from "lucide-react";
import { errorMessage } from "../api";
import type { MentorAction, MentorAdvice, MentorMode, Session } from "../types";
import "../mentor-design.css";

export function ConversationCoach({
  session,
  busy,
  onAdvice,
  onMode,
  onAdd,
}: {
  session: Session;
  busy: boolean;
  onAdvice: (action: MentorAction, messageId?: string) => Promise<MentorAdvice>;
  onMode: (mode: MentorMode) => Promise<void>;
  onAdd: (text: string) => "added" | "existing" | "limit";
}) {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<MentorAction | "mode" | null>(null);
  const [advice, setAdvice] = useState<MentorAdvice | null>(null);
  const context = session.messages.at(-1)?.id;
  const mode = session.mentor_state?.mode ?? "guided";
  const lastReply = [...session.messages]
    .reverse()
    .find(
      (message) =>
        message.role === "user" &&
        (!message.kind || message.kind === "message"),
    );
  const saved = session.mentor_state?.last_advice;
  const currentAdvice =
    advice?.context_message_id === context
      ? advice
      : saved?.context_message_id === context
        ? saved
        : null;
  useEffect(() => {
    setNotice("");
    setError("");
    setAdvice(null);
  }, [context]);

  async function ask(action: MentorAction) {
    setError("");
    setNotice("");
    setPending(action);
    try {
      setAdvice(
        await onAdvice(action, action === "review" ? lastReply?.id : undefined),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }
  async function changeMode(next: MentorMode) {
    if (next === mode) return;
    setError("");
    setNotice("");
    setPending("mode");
    try {
      await onMode(next);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(null);
    }
  }
  const disabled = busy || pending !== null;

  return (
    <section
      className="conversation-coach"
      aria-label="Разговорчик — помощник по переговорам"
    >
      <div className="coach-header">
        <div className="coach-identity">
          <span className="coach-icon" aria-hidden="true">
            <MessageCircle size={21} strokeWidth={1.6} />
          </span>
          <div>
            <strong>Разговорчик</strong>
            <span>Ваш помощник в практике</span>
          </div>
        </div>
        <div
          className="coach-modes"
          role="group"
          aria-label="Помощь в тренировке"
        >
          <button
            type="button"
            aria-pressed={mode === "guided"}
            disabled={disabled}
            onClick={() => void changeMode("guided")}
          >
            С наставником
          </button>
          <button
            type="button"
            aria-pressed={mode === "independent"}
            disabled={disabled}
            onClick={() => void changeMode("independent")}
          >
            Самостоятельно
          </button>
        </div>
      </div>
      {mode === "guided" ? (
        <details className="coach-help">
          <summary>
            <span>Нужна идея для ответа?</span>
            <ChevronDown size={16} aria-hidden="true" />
          </summary>
          <p className="coach-intro">
            Выберите, насколько помочь. Клиент не видит эти советы.
          </p>
          <div className="coach-actions">
            <button
              type="button"
              disabled={disabled}
              onClick={() => void ask("hint")}
            >
              <Lightbulb size={16} />
              Дай намёк
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => void ask("example")}
            >
              <PencilLine size={16} />
              Покажи пример
            </button>
            <button
              type="button"
              disabled={disabled || !lastReply}
              title={
                !lastReply
                  ? "Сначала отправьте свою реплику клиенту"
                  : undefined
              }
              onClick={() => void ask("review")}
            >
              <Search size={16} />
              Разбери мой ответ
            </button>
          </div>
          {!lastReply && (
            <p className="coach-footnote">
              Разбор появится, когда вы отправите первую реплику.
            </p>
          )}
          {pending && pending !== "mode" && (
            <p className="coach-working" role="status">
              <LoaderCircle size={15} className="spin" />
              Подбираем совет к этому ходу…
            </p>
          )}
          {currentAdvice && (
            <div className="coach-advice" aria-live="polite" aria-atomic="true">
              <strong>{currentAdvice.title}</strong>
              <p>{currentAdvice.text}</p>
              {currentAdvice.message_id && (
                <blockquote className="coach-reviewed-reply">
                  {
                    session.messages.find(
                      (message) => message.id === currentAdvice.message_id,
                    )?.text
                  }
                </blockquote>
              )}
              {currentAdvice.example && (
                <>
                  <blockquote>{currentAdvice.example}</blockquote>
                  <button
                    type="button"
                    className="coach-use-example"
                    disabled={disabled}
                    onClick={() => {
                      const result = onAdd(currentAdvice.example!);
                      setNotice(
                        result === "added"
                          ? "Пример добавлен в черновик. Отредактируйте его перед отправкой."
                          : result === "existing"
                            ? "Этот пример уже есть в вашем черновике."
                            : "В черновике не хватает места. Сократите текст и попробуйте ещё раз.",
                      );
                    }}
                  >
                    <ArrowUpLeft size={16} />
                    Вставить в черновик
                  </button>
                </>
              )}
              <span className="coach-method">
                Совет по правилам тренировки · не оценка профессионализма
              </span>
            </div>
          )}
          {notice && (
            <p className="coach-notice" role="status">
              {notice}
            </p>
          )}
          <p className="coach-footnote">
            Использованные подсказки отмечаются в прогрессе. Можно ответить
            своими словами.
          </p>
        </details>
      ) : (
        <p className="coach-independent">
          Подсказки выключены. Обратная связь будет в итоговом разборе.
          {session.mentor_state?.used
            ? " Помощь, использованная ранее, сохранится в истории этой попытки."
            : ""}
        </p>
      )}
      {error && (
        <p className="coach-error" role="alert">
          {error} Повторите выбранное действие.
        </p>
      )}
    </section>
  );
}
