import { NextRequest, NextResponse } from "next/server";

const ADMIN_COOKIE = "s2d_admin";
const LOGIN_PATH = "/admin/login";

export const config = {
    matcher: ["/admin/:path*"],
};

export function proxy(request: NextRequest) {
    const { pathname } = request.nextUrl;

    if (pathname.startsWith(LOGIN_PATH)) {
        return NextResponse.next();
    }

    const cookie = request.cookies.get(ADMIN_COOKIE);
    if (!cookie) {
        const loginUrl = request.nextUrl.clone();
        loginUrl.pathname = LOGIN_PATH;
        loginUrl.searchParams.set("next", pathname + request.nextUrl.search);
        return NextResponse.redirect(loginUrl);
    }

    return NextResponse.next();
}
