import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  // The API checks the actual file size. Reject excessive multipart bodies
  // here so Next never forwards a truncated request and returns a proxy 500.
  const length = Number(request.headers.get("content-length"));
  if (request.method === "POST" && length > 51 * 1024 * 1024) {
    return NextResponse.json(
      { detail: "Choose a non-empty audio file up to 50 MB." },
      { status: 413, headers: { "Cache-Control": "no-store" } },
    );
  }
  return NextResponse.next();
}

export const config = { matcher: "/api/uploads" };
