"use client";

import { useEffect, useState } from "react";

/**
 * Capture page-level keystrokes into a filter buffer.
 *
 * Any printable single-character key appends to the buffer; Backspace pops
 * the last char; Escape clears. Keystrokes are ignored while the user is
 * focused on an input/textarea/select/contenteditable so we never fight
 * other inputs. Modifier-key combos (Ctrl/Cmd/Alt) are also ignored.
 *
 * Use on any page that wants "just start typing to filter".
 */
export function useTypeAheadFilter(): { buffer: string; clear: () => void } {
  const [buffer, setBuffer] = useState("");

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        target?.isContentEditable
      ) {
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.key === "Escape") {
        if (buffer) e.preventDefault();
        setBuffer("");
        return;
      }
      if (e.key === "Backspace") {
        if (buffer.length === 0) return;
        e.preventDefault();
        setBuffer((b) => b.slice(0, -1));
        return;
      }
      if (e.key.length === 1) {
        e.preventDefault();
        setBuffer((b) => b + e.key);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [buffer]);

  return { buffer, clear: () => setBuffer("") };
}
