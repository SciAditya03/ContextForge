"use client";
import { useCallback, useEffect, useState } from "react";

interface State<T> {
  key: string | null;
  data: T | null;
  error: string | null;
}

/** Minimal data-fetching hook: { data, error, loading, reload, setData }. Re-runs when `deps` change. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify([...deps, nonce]);
  const [state, setState] = useState<State<T>>({ key: null, data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    fn().then(
      (data) => !cancelled && setState({ key, data, error: null }),
      (e: unknown) => !cancelled && setState((s) => ({ key, data: s.data, error: e instanceof Error ? e.message : String(e) })),
    );
    return () => {
      cancelled = true;
    };
    // `fn` is intentionally excluded: callers pass an inline closure; `deps` define identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const setData = useCallback((data: T) => setState((s) => ({ ...s, data })), []);
  return { data: state.data, error: state.key === key ? state.error : null, loading: state.key !== key, reload, setData };
}
