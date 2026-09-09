export type SafeLoadResult<T> = {
  ok: true;
  data: T;
  error: null;
};

export type SafeLoadFailure = {
  ok: false;
  data: null;
  error: string;
};

export type SafeLoad<T> = SafeLoadResult<T> | SafeLoadFailure;

export async function safeLoad<T>(task: () => Promise<T>): Promise<SafeLoad<T>> {
  try {
    const data = await task();
    return { ok: true, data, error: null };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown runtime error";
    return { ok: false, data: null, error: message };
  }
}

