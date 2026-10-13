"use client";

import { useRef, type KeyboardEvent } from "react";

export type TabItem<T extends string> = { id: T; label: string };

type Props<T extends string> = {
  items: TabItem<T>[];
  selected: T;
  onSelect: (id: T) => void;
  label: string;
  /** Prefix for tab / panel ids: tabs are `${idPrefix}-tab-${id}`, panels `${idPrefix}-panel-${id}`. */
  idPrefix: string;
  className?: string;
};

export function tabId(prefix: string, id: string): string {
  return `${prefix}-tab-${id}`;
}

export function panelId(prefix: string, id: string): string {
  return `${prefix}-panel-${id}`;
}

/**
 * WAI-ARIA tablist with a roving tabindex: Tab enters and leaves the list at
 * the selected tab; Left/Right (and Up/Down), Home and End move between tabs
 * and select them (automatic activation).
 */
export function Tabs<T extends string>({ items, selected, onSelect, label, idPrefix, className = "chips" }: Props<T>) {
  const refs = useRef<Map<T, HTMLButtonElement>>(new Map());

  function focusAndSelect(index: number) {
    const item = items[(index + items.length) % items.length];
    if (!item) return;
    onSelect(item.id);
    refs.current.get(item.id)?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        focusAndSelect(index + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        focusAndSelect(index - 1);
        break;
      case "Home":
        event.preventDefault();
        focusAndSelect(0);
        break;
      case "End":
        event.preventDefault();
        focusAndSelect(items.length - 1);
        break;
      default:
        break;
    }
  }

  return (
    <div className={className} role="tablist" aria-label={label}>
      {items.map((item, index) => {
        const isSelected = item.id === selected;
        return (
          <button
            key={item.id}
            ref={(element) => {
              if (element) refs.current.set(item.id, element);
              else refs.current.delete(item.id);
            }}
            type="button"
            role="tab"
            id={tabId(idPrefix, item.id)}
            aria-controls={panelId(idPrefix, item.id)}
            aria-selected={isSelected}
            tabIndex={isSelected ? 0 : -1}
            className={`chip ${isSelected ? "active" : ""}`}
            onClick={() => onSelect(item.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
