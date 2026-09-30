import { NextRequest, NextResponse } from "next/server";

/**
 * Password gate for when the app is shared over a tunnel.
 *
 * Off unless SHARE_PASSWORD is set, so running locally stays a double-click with
 * no login. share.bat sets it; start.bat does not.
 *
 * This runs ahead of the /api rewrite, so the backend is covered by the same
 * gate — which matters because the backend itself has no auth and is only safe
 * while it stays bound to localhost.
 */

const REALM = 'Basic realm="Video AI Studio", charset="UTF-8"';

/** Compares without leaking length or position through timing. */
function sameSecret(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  // Fold the length difference into the result instead of returning early.
  let diff = x.length ^ y.length;
  const n = Math.max(x.length, y.length);
  for (let i = 0; i < n; i++) {
    diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  }
  return diff === 0;
}

function unauthorized(): NextResponse {
  return new NextResponse("이 주소는 비밀번호가 필요합니다. / Password required.", {
    status: 401,
    headers: {
      "WWW-Authenticate": REALM,
      "Cache-Control": "no-store",
    },
  });
}

export function middleware(req: NextRequest) {
  const expected = process.env.SHARE_PASSWORD;
  if (!expected) return NextResponse.next(); // local run: no gate

  const header = req.headers.get("authorization") ?? "";
  const [scheme, encoded] = header.split(" ");
  if (scheme !== "Basic" || !encoded) return unauthorized();

  let decoded: string;
  try {
    decoded = atob(encoded); // Edge runtime has no Buffer
  } catch {
    return unauthorized();
  }

  // "user:password" — the username is ignored, so any name works.
  const sep = decoded.indexOf(":");
  const supplied = sep === -1 ? "" : decoded.slice(sep + 1);
  return sameSecret(supplied, expected) ? NextResponse.next() : unauthorized();
}

export const config = {
  // Everything except Next's own static output. /api is deliberately included:
  // leaving it out would expose the whole backend through the tunnel.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
