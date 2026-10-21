import { useEffect, useRef, useState } from "react";

export type State<T> = { data: T; loading: boolean; error: unknown };

// runs `load` when `deps` change, aborting the previous call; `delay` debounces (typing)
export function useApi<T>(load: (signal: AbortSignal) => Promise<T>, empty: T, deps: unknown[], delay = 0): State<T> {
  const [state, setState] = useState<State<T>>({ data: empty, loading: true, error: null });
  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true, error: null }));
      load(ctrl.signal)
        .then((data) => setState({ data, loading: false, error: null }))
        .catch((e: Error) => {
          if (e.name !== "AbortError") setState({ data: empty, loading: false, error: e });
        });
    }, delay);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, deps);
  return state;
}

export type Pages<T> = { items: T[]; total: number; hasMore: boolean; loading: boolean; error: unknown; more: () => void };

// a list that grows page by page; everything restarts when `deps` change (the previous request is aborted)
export function useInfinite<T>(
  load: (page: number, signal: AbortSignal) => Promise<{ items: T[]; total: number; has_more: boolean }>,
  deps: unknown[],
  delay = 0,
): Pages<T> {
  const first = { items: [] as T[], page: 0, total: 0, hasMore: false, loading: true, error: null as unknown };
  const [s, setS] = useState(first);
  const ctrl = useRef<AbortController>();

  function fetchPage(page: number) {
    ctrl.current?.abort();
    const c = (ctrl.current = new AbortController());
    setS((p) => ({ ...p, loading: true, error: null }));
    load(page, c.signal)
      .then((r) => setS((p) => ({ items: page === 1 ? r.items : [...p.items, ...r.items], page, total: r.total, hasMore: r.has_more, loading: false, error: null })))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setS((p) => ({ ...p, loading: false, error: e }));
      });
  }

  useEffect(() => {
    setS(first);
    const timer = setTimeout(() => fetchPage(1), delay);
    return () => {
      clearTimeout(timer);
      ctrl.current?.abort();
    };
  }, deps);

  return { ...s, more: () => !s.loading && s.hasMore && fetchPage(s.page + 1) };
}
