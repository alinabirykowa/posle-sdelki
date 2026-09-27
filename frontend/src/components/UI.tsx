import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { ReplyMode } from "../types";
import { ArrowUpRight, Asterisk, Check, LoaderCircle, X } from "lucide-react";

export const money = (value: number) =>
  `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
export const number = (value: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value);

export function plural(value: number, forms: [string, string, string]) {
  const category = new Intl.PluralRules("ru-RU").select(value);
  return forms[category === "one" ? 0 : category === "few" ? 1 : 2];
}

export function Brand({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand ${small ? "brand-small" : ""}`}>
      <svg
        className="studio-brand-mark"
        width="30"
        height="30"
        viewBox="0 0 30 30"
        fill="none"
        aria-hidden="true"
      >
        <path d="M4 5h13v13H9l-5 5V5Z" fill="currentColor" />
        <path d="M26 25H13V12h8l5-5v18Z" fill="#F15B35" />
      </svg>
      <span>
        после сделки<span className="brand-dot">.</span>
      </span>
    </span>
  );
}

export function Loading({
  label = "Загружаем пространство…",
}: {
  label?: string;
}) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={24} />
      <span>{label}</span>
    </div>
  );
}

export function ModeBadge({
  mode,
  replyMode = "rules",
  onClick,
}: {
  mode: "demo" | "live";
  replyMode?: ReplyMode;
  onClick?: () => void;
}) {
  const label =
    mode === "demo"
      ? "Демо-сценарий"
      : replyMode === "generated"
        ? "AI-собеседник"
        : "AI-анализ";
  if (!onClick) {
    return (
      <span className={`mode-badge ${mode}`}>
        <span className="status-dot" />
        {label}
      </span>
    );
  }
  return (
    <button className={`mode-badge ${mode}`} onClick={onClick} type="button">
      <span className="status-dot" />
      {label}
    </button>
  );
}

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = old;
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? "modal-wide" : ""}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      aria-labelledby="modal-title"
    >
      <div className="modal-inner">
        <div className="modal-heading">
          <h2 id="modal-title">{title}</h2>
          <button
            className="icon-button"
            aria-label="Закрыть"
            onClick={onClose}
          >
            <X size={22} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

export function HeroArt() {
  return (
    <div
      className="deal-preview"
      role="img"
      aria-label="Пример из кейса: клиент согласен, но 160 часов работы не помещаются в доступные 120. Перегрузка — 40 часов."
    >
      <div className="preview-orbit" aria-hidden="true" />
      <div className="preview-spark" aria-hidden="true">
        <Asterisk size="1em" />
      </div>
      <div className="promise-sheet" aria-hidden="true">
        <div className="preview-label">
          01 / НА СЛОВАХ <Check size={16} />
        </div>
        <p>
          «Добавим всё.
          <br />
          Срок оставим»
        </p>
        <div className="promise-signed">
          <span className="signature">Договорились</span>
          <ArrowUpRight size={18} aria-hidden="true" />
        </div>
      </div>
      <div className="reality-sheet" aria-hidden="true">
        <div className="preview-label">
          02 / НА ДЕЛЕ <ArrowUpRight size={17} />
        </div>
        <div className="reality-value">
          <strong>
            160<span> ч</span>
          </strong>
          <span className="overload-tag">+40 ч к ресурсу</span>
        </div>
        <div className="capacity-track">
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className="capacity-caption">
          <span>Ресурс команды</span>
          <b>120 ч</b>
        </div>
        <p>Согласие есть. Времени — нет.</p>
      </div>
      <span className="preview-footnote" aria-hidden="true">
        ПРИМЕР ИЗ КЕЙСА «ЕЩЁ НЕМНОГО РАБОТЫ»
      </span>
    </div>
  );
}

export function CaseArt({ variant }: { variant: "scope" | "discount" }) {
  return (
    <div className={`case-visual ${variant}`} aria-hidden="true">
      {variant === "scope" ? (
        <>
          <div className="scope-stack stack-one" />
          <div className="scope-stack stack-two" />
          <div className="scope-stack stack-three">
            <span>ЕЩЁ НЕМНОГО</span>
            <strong>
              +40<small>ч</small>
            </strong>
            <ArrowUpRight size={23} />
          </div>
        </>
      ) : (
        <>
          <div className="price-orbit" />
          <div className="price-disc">
            <span>ТОТ ЖЕ ОБЪЁМ</span>
            <strong>−⅓</strong>
            <span>ДРУГАЯ ЦЕНА</span>
          </div>
        </>
      )}
    </div>
  );
}
