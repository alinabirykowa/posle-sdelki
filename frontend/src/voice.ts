export type RecognitionResult = {
  isFinal: boolean;
  0: { transcript: string };
};
export type RecognitionEvent = { results: ArrayLike<RecognitionResult> };
export type BrowserRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onaudioend: (() => void) | null;
  onend: (() => void) | null;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
export type RecognitionConstructor = new () => BrowserRecognition;
export type CaptureStatus = "idle" | "starting" | "listening" | "processing";

export function recognitionConstructor(): RecognitionConstructor | undefined {
  if (typeof window === "undefined" || !window.isSecureContext) return;
  const speechWindow = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
}

export function recognitionError(code: string) {
  const messages: Record<string, string> = {
    "not-allowed":
      "Браузер не разрешил микрофон. Разрешите доступ в настройках сайта или напишите ответ ниже.",
    "service-not-allowed":
      "Распознавание речи недоступно в этом браузере. Продолжайте письменно.",
    "audio-capture":
      "Микрофон недоступен. Проверьте подключение и разрешения или напишите ответ ниже.",
    "no-speech":
      "Речь не распознана. Попробуйте ещё раз или напишите ответ ниже.",
    network:
      "Сервис распознавания недоступен. Проверьте соединение или продолжайте письменно.",
    "language-not-supported":
      "Браузер не поддерживает распознавание русского языка. Продолжайте письменно.",
  };
  return (
    messages[code] ||
    "Не удалось распознать речь. Можно повторить запись или продолжить письменно."
  );
}

/** A stopped page must never receive a late transcript from an old microphone run. */
export function createVoiceCapture(
  Constructor: RecognitionConstructor,
  handlers: {
    status: (status: CaptureStatus) => void;
    result: (final: string, interim: string) => void;
    error: (message: string) => void;
  },
) {
  let current: BrowserRecognition | null = null;
  let generation = 0;
  function abort(notify = true) {
    const previous = current;
    current = null;
    generation += 1;
    if (previous) {
      previous.onstart = previous.onaudioend = previous.onend = null;
      previous.onresult = previous.onerror = null;
      try {
        previous.abort();
      } catch {
        /* Some engines already ended. */
      }
    }
    if (notify) handlers.status("idle");
  }
  return {
    start() {
      abort(false);
      const token = generation;
      let recognition: BrowserRecognition;
      try {
        recognition = new Constructor();
      } catch {
        handlers.status("idle");
        handlers.error(recognitionError("unavailable"));
        return;
      }
      current = recognition;
      const valid = () => current === recognition && generation === token;
      recognition.lang = "ru-RU";
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        if (valid()) handlers.status("listening");
      };
      recognition.onaudioend = () => {
        if (valid()) handlers.status("processing");
      };
      recognition.onresult = (event) => {
        if (!valid()) return;
        const final: string[] = [];
        const interim: string[] = [];
        for (let index = 0; index < event.results.length; index += 1) {
          const result = event.results[index];
          (result.isFinal ? final : interim).push(result[0].transcript.trim());
        }
        handlers.result(final.join(" ").trim(), interim.join(" ").trim());
      };
      recognition.onerror = (event) => {
        if (!valid()) return;
        abort();
        if (event.error !== "aborted")
          handlers.error(recognitionError(event.error));
      };
      recognition.onend = () => {
        if (!valid()) return;
        current = null;
        generation += 1;
        handlers.status("idle");
      };
      handlers.status("starting");
      try {
        recognition.start();
      } catch {
        abort();
        handlers.error(recognitionError("unavailable"));
      }
    },
    stop() {
      if (!current) return;
      handlers.status("processing");
      try {
        current.stop();
      } catch {
        abort();
      }
    },
    abort,
  };
}

export function appendTranscript(
  draft: string,
  transcript: string,
): string | null {
  const result = [draft.trimEnd(), transcript.trim()]
    .filter(Boolean)
    .join("\n");
  return result.length <= 2000 ? result : null;
}
