# Practice Platform — Design Note

Status: **scoped, not started.** Implementation is blocked until the
production readiness checklist in `CLAUDE.md` is fully cleared. This note
exists so the seams are right whenever that work begins — same convention
as Phase 2+ notes in `architecture.md` §8.

## 1. What this is

A second, public-facing product surface alongside the invite-only exam
platform: open sign-up, HackerRank-style practice — browse questions by
topic/difficulty, submit code, get a verdict, track streaks/history.
It is additive. Nothing about the exam platform's invite-only model,
blueprint engine, or live follow-up channel changes.

Decisions already made (2026-07-25):

- **Access:** open public sign-up (email+password or Google sign-in),
  not gated by invite. This is a *third* user plane, not a variant of
  candidate or examiner auth.
- **Content:** reuses the existing question bank and judge pipeline —
  no separate question store. Questions are opted into practice
  explicitly (see §3), not exposed by default.
- **Sequencing:** design only for now. No code until the readiness
  checklist clears — see `CLAUDE.md` "Production readiness."

## 2. Third user plane — do not mix with existing two

Hard rule 3 says candidate auth and examiner auth must never mix token
types. A public practice user is a **third** kind, equally not to be
confused with either:

| Plane | Who | Auth | Token aud |
|---|---|---|---|
| Examiner | org staff | password + TOTP | `examiner` |
| Candidate | invited email | Google OIDC, invite-bound | `candidate` |
| Practice (new) | anyone | self-serve email/password or Google, no invite | `practice` |

Gateway must reject a `practice` token on any exam/examiner route and
vice versa, same as it already does between the two existing planes.
Practice sign-up is *not* OIDC-invite-bound — there is no invited email
to match against, so the existing invite-consumption logic doesn't
apply here and shouldn't be reused or generalized for it.

## 3. Where this lives (service boundary)

Proposal: a new `services/practice/` service, not an extension of
`services/exam/` or `services/question/` — per hard rule 1 (no
cross-service imports), it owns its own bounded context:

- Practice user accounts, auth, profile.
- Practice submission history, streaks, per-topic progress.
- (Later) leaderboards, badges.

It does **not** own question content. It reads questions from
`services/question/` over HTTP, same pattern exam service already
uses. It submits to the judge queue the same way exam service does.

**Open question requiring sign-off before implementation** (per
CLAUDE.md "When unsure: ... changing the DB schema of another
service"): question service needs a `practice_eligible` flag (or a
review/publish step) on question versions so practice only surfaces
questions an author has explicitly cleared for public use — exam
questions must never leak into practice by default. This is a schema
change to `services/question/`, owned by that service's team/migration,
not something practice can bolt on unilaterally.

## 4. Multi-tenancy (hard rule 4)

Every tenant table carries `org_id` today; there is no notion of an
org-less row anywhere in the schema or repository layer. Practice users
aren't a customer org, but breaking the `org_id` invariant to special-case
them is worse than the alternative: reserve a single sentinel org row
(e.g. `org_id` for a well-known "public" org, seeded once) that all
practice accounts and practice submissions belong to. Every existing
repository function keeps working unmodified — `org_id` is just always
that one value for this plane. This needs explicit sign-off since it's
a judgment call on how far to stretch an existing invariant rather than
add an exception to it.

## 5. Judge pipeline reuse

Judge workers are already generic (submission in, verdict out) and
shouldn't need sandbox changes. The open piece is the **verdict return
path**: today the judge publishes verdicts back to a queue the exam
service consumes and persists. Practice needs its own consumer. Two
options, to decide before implementation:

- (a) job payload carries an `origin_service` field; judge publishes to
  a per-origin verdict queue (`exam-verdicts`, `practice-verdicts`).
- (b) single shared verdict topic; both exam and practice services
  consume and filter by a `source` field, discarding what's not theirs.

(a) keeps queue contracts simple and matches "services never import
each other's code" more literally (no fan-out/filter logic shared
between consumers). Leaning (a), but this is a judge-service contract
change and should get explicit sign-off per CLAUDE.md before coding,
same as the sandbox-limits rule.

## 6. Not decided yet (flag before implementation, don't assume)

- Rate limiting / abuse prevention for anonymous-adjacent public
  sign-up hitting the judge queue (a practice-only concern; exam has no
  equivalent since candidates are invite-scarce by construction).
- Whether practice submissions get S3-stored replays like exam sessions,
  or are ephemeral.
- Leaderboard/streak scope: global or per-topic — affects schema shape,
  easier to decide once judge/queue plumbing (§5) is settled.

## 7. Sequencing

Do not start any of the above until the `CLAUDE.md` production
readiness checklist is cleared — this is a net-new public-facing attack
surface (open sign-up, unauthenticated-until-signup traffic hitting the
judge queue) and should not go in ahead of TLS, RS256, and the Redis
key-prefix migration that checklist tracks.
