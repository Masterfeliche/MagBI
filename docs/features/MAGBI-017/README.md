# Feature: MAGBI-017 - Landing page and sign-in

Source: the approved mockup "MagBI Landing & Login" (https://claude.ai/artifact/EkyUxzHGkyroqbbFiSd3JJ). MagBI is presented as its own product; MSD ERP appears as a customer story.

## 1. Analysis

- `/` redirected straight to `/workspaces`, and there was no sign-in page: MagBI only worked in dev mode, where a request without a token is treated as an admin.
- The backend already issues tokens (`POST /api/v1/auth/login`); the web client already sends the token it finds in browser storage.
- The audit table exists but nothing writes sign-ins to it, so the page must not claim sign-ins are recorded.

## 2. What was built

| Part | Files |
|------|-------|
| Landing page at `/` | `web/src/site/LandingPage.tsx`, `site.css`, `Logo.tsx` |
| Copy and placeholders in one place | `web/src/site/content.ts` |
| Sign-in at `/login`, with wrong-password and other error states | `web/src/site/LoginPage.tsx` |
| Session: token kept until the browser closes, or across restarts with "Keep me signed in" | `web/src/shared/session.ts`, `web/src/shared/api.ts` |
| Sign out in the app's top bar | `web/src/workspace/AppShell.tsx` |
| After sign-in, return only to a same-site path (`?next=`) | `safeNext` in `LoginPage.tsx`, tested in `site.test.ts` |

Placeholders to fill before launch, all in `content.ts`: company name, contact email and phone, the customer quote with its author, every bracketed price and the yearly discount.

## 3. Checks (31 Oct 2026, headless Chrome)

- Landing at 1440 and 390 wide, login at 1440 and 390: no sideways scroll, no clipped text, no "undefined" or NaN.
- Wrong password: "That email and password don't match. Check both and try again." and the password field marked invalid.
- Right password: lands on `/workspaces`; token in session storage only when "Keep me signed in" is off.
- Sign out: token cleared, back to `/login`.
- 56 frontend tests pass.

## 4. Not in this feature

- Requiring sign-in for the app pages (production turns off the dev bypass; the pages do not yet redirect to `/login` on a 401).
- Lockout after repeated wrong passwords, password reset, single sign-on.
- Writing sign-ins to the audit log.
