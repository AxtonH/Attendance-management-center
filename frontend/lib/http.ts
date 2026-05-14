import { z } from "zod";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}

/**
 * Typed GET helper. Builds the URL with query params, parses the response
 * through the supplied Zod schema, and returns the parsed value.
 *
 * Single seam between the app and the backend — every feature's api.ts
 * is built on this so headers, error handling, and base URL stay consistent.
 */
export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  params: Record<string, string | number | undefined> = {},
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }

  const res = await fetch(url.toString(), {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });

  if (!res.ok) {
    throw new ApiError(`Request failed: ${path}`, res.status);
  }

  const json = await res.json();
  return schema.parse(json);
}
