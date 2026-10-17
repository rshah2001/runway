import { useCallback, useEffect, useState } from 'react';

type State<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Runs an API call on mount and whenever `key` changes; `reload()` re-runs it (pull-to-refresh).
 * State is only set from the promise callbacks, and a stale response (screen left, key changed)
 * is dropped rather than overwriting newer data.
 */
export function useLoad<T>(fn: () => Promise<T>, key = ''): State<T> & { reload: () => void } {
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });

  useEffect(() => {
    let live = true;
    fn().then(
      (data) => live && setState({ data, error: null, loading: false }),
      (e: unknown) => live && setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e), loading: false })),
    );
    return () => {
      live = false;
    };
    // `fn` is a fresh closure every render; `key` and `nonce` are what decide when to refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce]);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true }));
    setNonce((n) => n + 1);
  }, []);

  return { ...state, reload };
}

/** The HTTP status in an api.ts error message ("POST /x failed: 503"), if any. */
export const httpStatus = (message: string): number | null => Number(message.match(/failed: (\d{3})/)?.[1]) || null;
