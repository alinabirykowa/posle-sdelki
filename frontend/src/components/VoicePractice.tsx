import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  ArrowDown,
  Clock3,
  Mic,
  Pause,
  Play,
  RotateCcw,
  Square,
  Volume2,
} from "lucide-react";
import type { Message } from "../types";
import {
  appendTranscript,
  createVoiceCapture,
  recognitionConstructor,
} from "../voice";
import type { CaptureStatus } from "../voice";
import "../voice-practice.css";

type VoicePracticeProps = {
  clientName: string;
  message?: Message;
  disabled: boolean;
  interruptKey: number;
  draft: string;
  onUseTranscript: (text: string) => boolean;
  onTextMode: () => void;
};

export function VoicePractice({
  clientName,
  message,
  disabled,
  interruptKey,
  draft,
  onUseTranscript,
  onTextMode,
}: VoicePracticeProps) {
  const [captureStatus, setCaptureStatus] = useState<CaptureStatus>("idle");
  const [playback, setPlayback] = useState<"idle" | "loading" | "speaking">(
    "idle",
  );
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const capture = useRef<ReturnType<typeof createVoiceCapture> | null>(null);
  const playbackGeneration = useRef(0);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const canRecognize = Boolean(recognitionConstructor());
  const canSpeak =
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    "SpeechSynthesisUtterance" in window;
  const capturing = captureStatus !== "idle";
  const active = captureStatus === "listening" || playback === "speaking";
  const canInsert =
    Boolean(transcript.trim()) && appendTranscript(draft, transcript) !== null;

  const stopAll = useCallback((notify = true) => {
    capture.current?.abort(notify);
    capture.current = null;
    playbackGeneration.current += 1;
    if (utteranceRef.current) {
      utteranceRef.current.onstart =
        utteranceRef.current.onend =
        utteranceRef.current.onerror =
          null;
      utteranceRef.current = null;
    }
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    if (notify) {
      setCaptureStatus("idle");
      setPlayback("idle");
      setInterim("");
    }
  }, []);

  useEffect(() => {
    if (!canSpeak) return;
    const refreshVoices = () => setVoices(window.speechSynthesis.getVoices());
    refreshVoices();
    window.speechSynthesis.addEventListener("voiceschanged", refreshVoices);
    return () =>
      window.speechSynthesis.removeEventListener(
        "voiceschanged",
        refreshVoices,
      );
  }, [canSpeak]);

  useEffect(() => {
    stopAll();
  }, [disabled, interruptKey, message?.id, stopAll]);

  useEffect(() => {
    const onHidden = () => {
      if (document.hidden) stopAll();
    };
    const onLeave = () => stopAll();
    document.addEventListener("visibilitychange", onHidden);
    window.addEventListener("hashchange", onLeave);
    window.addEventListener("pagehide", onLeave);
    const dialogs = new MutationObserver(() => {
      if (document.querySelector("dialog[open]")) stopAll();
    });
    dialogs.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open"],
    });
    return () => {
      dialogs.disconnect();
      document.removeEventListener("visibilitychange", onHidden);
      window.removeEventListener("hashchange", onLeave);
      window.removeEventListener("pagehide", onLeave);
      stopAll(false);
    };
  }, [stopAll]);

  function listen() {
    if (disabled || utteranceRef.current) return;
    const Constructor = recognitionConstructor();
    if (!Constructor) return;
    stopAll();
    setError("");
    const prefix = transcript.trim();
    const next = createVoiceCapture(Constructor, {
      status: (status) => {
        setCaptureStatus(status);
        if (status === "idle") {
          setInterim("");
        }
      },
      result: (final, pending) => {
        const combined = [prefix, final].filter(Boolean).join(" ");
        setTranscript(combined.slice(0, 2000));
        setInterim(pending);
        if (combined.length >= 2000) {
          next.abort();
          setError(
            "Достигнут лимит 2000 символов. Проверьте и сократите ответ перед отправкой.",
          );
        }
      },
      error: setError,
    });
    capture.current = next;
    next.start();
  }

  function speak() {
    if (disabled || capturing || !canSpeak || !message) return;
    stopAll();
    setError("");
    const voice = voices.find((candidate) =>
      /^ru(?:-|_)/i.test(candidate.lang),
    );
    if (voices.length > 0 && !voice) {
      setError(
        "На устройстве нет русского голоса для озвучивания. Текст клиента доступен в переписке ниже.",
      );
      return;
    }
    const token = playbackGeneration.current;
    const utterance = new SpeechSynthesisUtterance(message.text);
    utterance.lang = "ru-RU";
    utterance.rate = 1;
    if (voice) utterance.voice = voice;
    utteranceRef.current = utterance;
    const isCurrent = () =>
      playbackGeneration.current === token &&
      utteranceRef.current === utterance;
    utterance.onstart = () => {
      if (isCurrent()) setPlayback("speaking");
    };
    utterance.onend = () => {
      if (!isCurrent()) return;
      utteranceRef.current = null;
      setPlayback("idle");
    };
    utterance.onerror = (event) => {
      if (!isCurrent()) return;
      utteranceRef.current = null;
      setPlayback("idle");
      if (event.error !== "canceled" && event.error !== "interrupted") {
        setError(
          "Озвучивание недоступно. Прочитайте реплику клиента в переписке ниже.",
        );
      }
    };
    setPlayback("loading");
    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      stopAll();
      setError("Браузер не смог озвучить реплику. Продолжайте по тексту ниже.");
    }
  }

  const status = disabled
    ? "Голос на паузе"
    : playback === "speaking"
      ? "Клиент говорит"
      : playback === "loading"
        ? "Готовим озвучивание…"
        : captureStatus === "starting"
          ? "Ожидаем микрофон…"
          : captureStatus === "listening"
            ? "Слушаем ваш ответ"
            : captureStatus === "processing"
              ? "Распознаём речь…"
              : "Ваш ход — вслух";

  return (
    <section
      className={`voice-practice ${active ? "is-active" : ""} ${captureStatus === "listening" ? "is-listening" : ""}`}
      aria-label="Голосовая практика"
    >
      <div className="voice-stage">
        <div className="voice-stage-heading">
          <span>ГОЛОСОВАЯ ПРАКТИКА</span>
          <span>RU</span>
        </div>
        <div className="voice-wave" aria-hidden="true">
          {Array.from({ length: 17 }, (_, index) => (
            <i
              key={index}
              style={
                {
                  "--bar": `${20 + ((index * 13) % 31)}px`,
                  "--delay": `${index * -0.12}s`,
                } as CSSProperties
              }
            />
          ))}
        </div>
        <strong className="voice-status" role="status">
          {status}
        </strong>
        <p>{clientName} · реплика за репликой</p>
        <div className="voice-controls">
          {playback !== "idle" ? (
            <button
              onClick={() => stopAll()}
              className="voice-control secondary"
            >
              <Square size={15} /> Остановить голос
            </button>
          ) : (
            <button
              onClick={speak}
              disabled={disabled || capturing || !canSpeak || !message}
              className="voice-control secondary"
            >
              <Volume2 size={17} /> Послушать клиента
            </button>
          )}
          {capturing ? (
            <button
              onClick={() =>
                captureStatus === "listening"
                  ? capture.current?.stop()
                  : stopAll()
              }
              className="voice-control primary"
            >
              <Square size={15} />
              {captureStatus === "listening" ? "Закончить ответ" : "Отменить"}
            </button>
          ) : (
            <button
              onClick={listen}
              disabled={disabled || !canRecognize || playback !== "idle"}
              className="voice-control primary"
            >
              <Mic size={17} /> Ответить голосом
            </button>
          )}
        </div>
      </div>
      <div className="voice-workbench">
        {!canRecognize && (
          <p className="voice-fallback">
            В этом браузере распознавание речи недоступно. Можно слушать
            клиента, если доступна озвучка, и отвечать письменно.{" "}
            <button onClick={onTextMode}>Перейти к тексту</button>
          </p>
        )}
        {!canSpeak && canRecognize && (
          <p className="voice-fallback">
            Браузер не поддерживает озвучивание. Реплики клиента остаются в
            переписке.
          </p>
        )}
        {(transcript || interim || capturing) && (
          <div className="voice-transcript">
            <label htmlFor="voice-transcript">
              Распознанный ответ <span>Проверьте перед отправкой</span>
            </label>
            <textarea
              id="voice-transcript"
              value={transcript}
              onChange={(event) => setTranscript(event.target.value)}
              disabled={capturing || disabled}
              placeholder="Здесь появится ваша реплика…"
              rows={3}
              maxLength={2000}
            />
            {interim && <p className="voice-interim">{interim}</p>}
            {!capturing && transcript.trim() && (
              <div className="voice-transcript-actions">
                <button
                  disabled={disabled || !canInsert}
                  onClick={() => {
                    if (onUseTranscript(transcript)) {
                      setTranscript("");
                      setInterim("");
                      setError("");
                    }
                  }}
                >
                  <ArrowDown size={15} /> Добавить в ответ
                </button>
                <span>
                  {canInsert
                    ? "Отправка — после вашей проверки"
                    : "Вместе с черновиком получится больше 2000 символов"}
                </span>
              </div>
            )}
          </div>
        )}
        {error && (
          <p className="voice-error" role="alert">
            {error}
          </p>
        )}
        <p className="voice-privacy">
          Микрофон включается только по кнопке. Распознавание может передавать
          аудио сервису браузера. Наш сервер получает только текст, который вы
          отправите.
        </p>
      </div>
    </section>
  );
}

export function PracticePace({
  durationMinutes,
  responseSeconds,
  messageId,
  turns,
  maxTurns,
  disabled,
}: {
  durationMinutes: number;
  responseSeconds: number;
  messageId?: string;
  turns: number;
  maxTurns?: number;
  disabled: boolean;
}) {
  const [remaining, setRemaining] = useState(responseSeconds);
  const [running, setRunning] = useState(true);
  const remainingRef = useRef(responseSeconds);
  useEffect(() => {
    remainingRef.current = responseSeconds;
    setRemaining(responseSeconds);
    setRunning(true);
  }, [messageId, responseSeconds]);
  useEffect(() => {
    if (!responseSeconds || !running || disabled || remainingRef.current <= 0)
      return;
    const deadline = Date.now() + remainingRef.current * 1000;
    const tick = () => {
      const next = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      remainingRef.current = next;
      setRemaining(next);
      if (next === 0) setRunning(false);
    };
    const interval = window.setInterval(tick, 250);
    return () => window.clearInterval(interval);
  }, [disabled, running, messageId, responseSeconds]);
  return (
    <div className="practice-pace">
      <div className="practice-duration">
        <Clock3 size={16} />
        <span>
          Ориентир <strong>{durationMinutes} минут</strong>
        </span>
        {maxTurns && (
          <span className="practice-turns">
            Ходы: {turns} / {maxTurns}
          </span>
        )}
      </div>
      {responseSeconds > 0 ? (
        <div className="practice-response">
          <span
            className={`pace-digits ${remaining === 0 ? "is-complete" : ""}`}
            aria-label={`Ориентир на ответ: ${remaining} секунд`}
          >{`0:${String(remaining).padStart(2, "0")}`}</span>
          <span>
            {remaining === 0
              ? "Ориентир пройден. Можно продолжить."
              : "Ориентир на ответ"}
          </span>
          <button
            disabled={disabled}
            onClick={() => {
              if (remaining === 0) {
                remainingRef.current = responseSeconds;
                setRemaining(responseSeconds);
                setRunning(true);
              } else setRunning((current) => !current);
            }}
            aria-label={
              remaining === 0
                ? "Повторить отсчёт"
                : running
                  ? "Приостановить отсчёт"
                  : "Продолжить отсчёт"
            }
          >
            {remaining === 0 ? (
              <RotateCcw size={15} />
            ) : running ? (
              <Pause size={15} />
            ) : (
              <Play size={15} />
            )}
          </button>
        </div>
      ) : (
        <span className="practice-no-rush">В своём темпе</span>
      )}
    </div>
  );
}
