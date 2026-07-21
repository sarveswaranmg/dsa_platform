# Candidate exam UI

React 18 + TypeScript + Vite. Covers the candidate flow: invite link →
Google sign-in → exam room (statement, Monaco editor, run/submit, verdicts,
server-synced countdown).

## Running

```bash
npm install
npm run dev            # http://localhost:5173, proxies /candidate → :8001
npm test               # Vitest + React Testing Library
npm run lint           # eslint
npx tsc --noEmit       # type check
```

`make dev` also starts this as the `frontend` compose service.

## Google sign-in

Sign-in uses real Google Identity Services and the backend independently
verifies the ID token (signature, issuer, audience) and that the email matches
the invited address — **there is no dev bypass anywhere**. To exercise the
sign-in leg locally you need your own OAuth client:

1. Create an OAuth 2.0 Web client in Google Cloud Console.
2. Add `http://localhost:5173` as an authorised JavaScript origin.
3. Set the client id in both places:

```bash
# frontend/.env.local
VITE_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com

# backend (compose reads this)
export GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
```

Without it, the invite page renders but the Google button is disabled and says
sign-in is not configured. The exam room itself can still be driven with a
directly-minted candidate exam token (see the exam service's
`create_candidate_exam_token`).

## Notes

- **Timer**: the countdown anchors on the server's `remaining_seconds` and
  re-anchors on every session refetch; the client wall clock is never trusted.
- **Run vs Submit**: *Run sample tests* grades only the question's sample
  cases; *Submit* grades the full suite.
- **RequirementsChangedBanner** is a Phase 2 seam — built and tested, never
  triggered in Phase 1.
