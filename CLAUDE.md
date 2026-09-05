# CLAUDE.md

Operational notes for Claude sessions working on this repo — dense, for an
agent, not prose for an external reader (that's what README.md is for).
Do not put server names, ISP/provider names, individual people's names,
or unpublished/draft project names here — same public-repo constraint as
z2r_autobench's/z0r-panel's own CLAUDE.md. `Server A`/`Server B`/etc. and
`Provider A`/`Provider B`/etc. are anonymized codenames, same convention.

## VOICE_UDP sandbox: `nfq_create_queue(): Operation not permitted` (2026-09-05)

- Live incident: `sandbox/start_sandbox.sh` ran `nfqws2` directly as root
  (required by the script's own `id -u == 0` check), with `--user=nobody`
  baked into `nfqws2_sandbox.conf.template` so `nfqws2` dropped its own
  privileges internally after binding. This had been silently broken —
  every VOICE_UDP sandbox apply failed at NFQUEUE creation, meaning every
  TCP-profile genome round ALSO silently failed the same way (they share
  the same sandbox process), for an unknown but likely long stretch of
  time — `experiments` showed zero new rows for any profile for the ~19
  hours immediately preceding the fix, despite `zenith-autorun.service`
  actively logging rounds the whole time (see "Silent DB-write gap"
  below for the full read on that symptom).
- **Root cause had three independent layers, found via `strace` against
  the live failure, in order:**
  1. `nfqws2` unconditionally drops itself to uid/gid 65534 (`nobody`) at
     startup, **regardless of whether `--user=` is even present** in its
     own config. Since the exec happens as root, root's ambient
     capabilities are irrelevant — file capabilities via `setcap` only
     take effect at the `execve()` boundary, and root already has every
     capability without needing any `setcap` grant at all. Once `nfqws2`
     drops itself internally, `nfq_create_queue()` runs at that point
     with whatever `capset()` managed to retain — which, run as root,
     should be fine in principle, but isn't (see layer 2). **Fix**:
     `start_sandbox.sh` now execs `nfqws2` directly as `nobody` via
     `runuser -u nobody --`, never as root, so the file-capability grant
     actually applies at `execve()` time instead of being moot.
     `--user=nobody` removed from the template — no longer meaningful
     once the exec itself already happens as `nobody`.
  2. `nfqws2`'s own PRIMARY internal `capset()` call explicitly requests
     `CAP_SETPCAP` **together with** `CAP_NET_ADMIN`/`CAP_NET_RAW`
     (apparently so it can shrink its own bounding set afterward via a
     `PR_CAPBSET_DROP` loop). A file-capability grant of only
     `cap_net_admin,cap_net_raw+eip` makes that first `capset()` fail
     with `EPERM` (can't request a capability — `CAP_SETPCAP` — that
     isn't already in the process's own permitted set), and `nfqws2`
     falls back to a reduced `capset()` that, empirically, does NOT leave
     the process able to bind NFQUEUE even though `capget()` immediately
     before the bind attempt shows `CAP_NET_ADMIN` present. **Fix**:
     `setcap` grant now includes `cap_setpcap` too:
     `setcap cap_net_admin,cap_net_raw,cap_setpcap+eip <resolved real binary path>`
     — this must be the **resolved** path (`readlink -f`), `setcap`
     refuses to operate on the `/opt/zapret2/nfq2/nfqws2` symlink
     directly.
  3. Even with (1)+(2) fixed, the specific failure hit live in this
     debugging session was a **third, independent cause**: an orphaned
     `nfqws2` sandbox process from an earlier manual test run (started
     successfully, but `start_sandbox.sh`'s own pidfile-existence check
     raced and reported it as failed) was still alive (`PPID=1`,
     daemonized) and still holding the sandbox's NFQUEUE number. The
     kernel returns **`EPERM`, not `EBUSY`**, when a second process tries
     to (re)bind an already-registered queue number — from the outside,
     indistinguishable from a capability problem. Confirmed via
     `cat /proc/net/netfilter/nfnetlink_queue` (shows `queue_number
     peer_portid ...` — a `peer_portid` with no matching live PID in
     `ps` is the tell) and `strace`'s `recvfrom()` on the netlink socket
     showing the kernel's own `NLMSG_ERROR` reply with `error=-EPERM`.
- **Fixes committed, both self-healing (idempotent, applied on every
  run, not just first install — same pattern as z2r_autobench's
  `ensure_wsrelay_user()`/`ensure_panel_runtime_grants()`):**
  - `start_sandbox.sh` now re-applies `setcap` (including `cap_setpcap`)
    to the resolved real binary on every single invocation — any
    reinstall/update of `zapret2`'s core binaries silently drops a new
    file in place with no capability grant at all, and the old grant on
    the old (now-replaced) inode is meaningless.
  - `stop_sandbox.sh` now ALSO `pkill -f "nfqws2 @$LIVE_CONF"` as a
    backup to the pidfile-based kill, specifically to prevent a repeat
    of layer 3 above (a future crash/race leaving a pidfile-less orphan
    that a future `start_sandbox.sh` run can't find and kill via the
    normal path).
  - pidfile moved from `sandbox/nfqws2_sandbox.pid` to
    `/tmp/zenith_nfqws2_sandbox.pid` — `sandbox/` is root-owned and
    `nobody` can't create a NEW file there (only append to an
    already-existing one, which is why the debug log kept working
    throughout this whole saga while the pidfile alone kept failing) —
    `/tmp`'s sticky bit lets `nobody` create its own pidfile safely.
- **Rollback**: `git revert` the three commits on this date touching
  `sandbox/start_sandbox.sh`/`sandbox/stop_sandbox.sh`/
  `sandbox/nfqws2_sandbox.conf.template` restores the previous
  root-exec + internal `--user=nobody` behavior — but that reintroduces
  the exact bug this section documents (confirmed broken, not a
  hypothetical), so only revert if the `runuser`-based approach itself
  turns out to cause a NEW, worse problem on some other server, not to
  "undo an experiment."
- **Silent DB-write gap, same incident**: while the sandbox was down,
  `zenith-autorun.service` kept logging normal-looking round output
  (`[N/20] PROFILE op=... -> ...`) with no visible error, for every
  profile, because `main.py` prints the mutation candidate BEFORE
  attempting to apply/test it — the actual apply failure only shows up
  in the (separate, not printed to the systemd journal by default)
  sandbox debug log. Once the sandbox was fixed, a manual
  `python3 main.py --profile <X> --rounds 3` for both VOICE_UDP and
  DS_TLS immediately showed real successful byte counts and real DB
  writes (`genome_scores.updated_at`/`experiments.tested_at` advancing),
  confirming the sandbox was the sole cause and the generation logic
  itself was never broken. No code fix applied for the "looks fine in
  the journal while failing" gap itself — flagged here as the same
  swallowed-failure class documented repeatedly in z2r_autobench's/this
  project's own history (see z2r_autobench's CLAUDE.md, "Lesson
  reinforced yet again" entries) — worth a `zenith_debug.sh`-style
  check next time this area is touched, not fixed ad hoc mid-incident.
- `zenith_debug.sh` (new, repo root) — one-shot read-only health report
  consolidating the manual diagnostic loop this whole incident required
  by hand (git branch/commit vs `main`, `zenith-autorun`/
  `zenith-promoter`/`zapret2` systemd+journal status, sandbox
  pidfile/queue/debug-log state, voice-bot port check, genome/experiment
  counts per profile from MySQL). Never restarts anything or touches
  `/opt/zapret2` — safe to run anytime, including in production. Run it
  first on any future "is generation/promotion actually working"
  question before doing anything by hand.

## `auto_promoter.py`: require a genuine improvement over the current champion before promoting (2026-09-05)

- **Motivating question, direct from the user**: what happens once the
  search plateaus — new genomes keep reaching the promotion threshold
  (`--min-pulls` runs, 100% success) but don't actually beat what's
  already live? Before this change: **nothing distinguished that case**.
  `_claim_promotable()`'s only criteria were "unpromoted" + "≥min_pulls
  runs" + "100% success", picking the best `avg_score` among ONLY those
  candidates — it never looked at the currently-live strategy's own
  score at all. A tied or even slightly worse new genome (fewer/noisier
  runs can still show 100% success with a lower `avg_score` than the
  incumbent) would still get promoted the moment it crossed the
  threshold, purely because the incumbent itself is no longer
  "unpromoted" and thus invisible to that query.
- **Why this matters, not just theoretical**: every promotion is a real
  production event — `zapret2` restart, a live-traffic check, and (on
  failure) an automatic rollback with its own real backup/restore cost
  (see `try_promote()`'s own docstring, point 3–5). Promoting a
  same-or-worse genome purely because it's new spends that whole cost
  (plus the "Ban / rate-limit avoidance" risk documented in
  z2r_autobench's CLAUDE.md — every live-check is real DPI-facing
  traffic) for zero benefit. Once the search plateaus, this would
  otherwise repeat indefinitely, once per interval tick, forever.
- **Fix**: `try_promote()` now reads the CURRENTLY live strategy number
  (`_get_strategy()`, already computed early — moved up, was previously
  read again mid-function) and looks up that number's own
  `genome_scores` row (new `_get_champion_score()` — joins on
  `gs.promoted_strategy = <live strategy number>` for this
  profile+environment) before accepting the best unpromoted candidate.
  If a champion row is found and the candidate's `avg_score` does NOT
  exceed it (`<=`, not `<` — ties count as "not better"), the claim is
  released immediately and `try_promote()` returns a distinct message
  naming both scores, instead of silently promoting a lateral/worse
  move.
- **Deliberately no margin/epsilon** — a candidate needs to be STRICTLY
  better, by any amount, not "better by more than some threshold". This
  directly answers the motivating question: identical-looking results
  are treated as "not an improvement" and skipped. If this turns out too
  strict in practice (e.g. noisy `avg_score` causing a genuinely
  equivalent genome to occasionally edge past `<=` by rounding alone),
  the fix is a small explicit margin constant, not silently loosening
  the comparison.
- **No champion row found** (current strategy was set manually, by
  `set_strategy_cli.sh` directly, or predates this scheme, or the
  strategy number was never itself promoted through this exact
  mechanism) — behavior is UNCHANGED from before this fix: the first
  candidate meeting the base threshold is promoted, same as always. This
  is intentional — there being nothing to compare against is not a
  reason to block promotion forever.
- **Rollback**: this is a single self-contained diff to
  `orchestrator/auto_promoter.py` (`_get_champion_score()` added,
  `_claim_promotable()`/`try_promote()` unchanged otherwise except the
  moved `old_locked` read and the new comparison block right after the
  claim). `git revert <this commit>` restores the exact prior behavior
  (promote first threshold-passing candidate, no champion comparison) —
  no schema change, no migration, nothing else depends on this.

## Live-check quarantine for genomes that keep failing production traffic checks (2026-09-05)

- **Found immediately after shipping the champion-comparison fix
  above**: manually re-running `auto_promoter.py --profile DS_TLS`
  promoted a genome (`47b030d9...`, family `multisplit`, avg_score 0.953
  in sandbox, 6/6 runs) that then failed the live traffic check against
  `discord.com` — confirmed via a manual repro with extended diagnostics
  (`curl -v`): the TLS ClientHello was genuinely sent, then silence —
  a clean timeout, not a TCP-level rejection. `_rollback()` correctly
  restored the previous config/strategy, so production was never left
  broken — but the underlying genome's `genome_scores` row is left
  exactly as it was before the attempt (`promoted_strategy` reset back
  to `NULL` by `_release_claim()`), meaning it remains the single
  highest-`avg_score` unpromoted candidate and **will be picked again
  on every future cycle, forever**, repeating the same real-traffic
  restart + guaranteed-failure + rollback cycle with no progress and no
  memory of the outcome.
- **Root cause of the actual live-check failure itself, not this
  repeated-selection problem**: already documented, not something this
  fix addresses. See README.md's own "Известный разрыв достоверности
  песочницы" section (referenced directly from `genome.py`'s
  `PROFILE_FILTERS` comment) — the sandbox tests a genome's
  `--lua-desync=` string directly, with no `--out-range=`/`--in-range=`
  wrapping and no `circular_locked` per-host cache semantics, both of
  which the real production block for every TCP profile actually uses.
  A genome can therefore pass the sandbox 100% of the time and still
  never actually get desync applied to it in production for certain
  packet-size buckets. **Deliberately NOT attempting to close this gap
  by reimplementing `--out-range=`/`--in-range=`/`circular_locked` in
  the sandbox** — `-s34228`/`-s32768`'s exact semantics aren't
  documented anywhere in this codebase, and this project's own stated
  principle (see README.md's VOICE_UDP section: "не мутируем то, что не
  можем объяснить документацией") is to not touch mechanisms it can't
  explain from documentation — doubly so in the sandbox code this same
  session just spent hours stabilizing. The live-check + rollback is the
  intentional, working safety net for this exact gap; what's missing is
  just memory of a genome having already tripped it.
- **Fix**: `genome_scores` gains `live_check_fails`/
  `live_check_quarantined_until` (migration
  `007_genome_live_check_quarantine.sql`, same idempotent
  information_schema-guarded pattern as 001-006). `try_promote()` now
  calls `_record_live_check_failure()` specifically in the
  `_real_traffic_check()`-failed branch (not other rollback causes like
  a failed restart or a `set_strategy_cli.sh` failure — those are
  infrastructure problems, not evidence the GENOME itself is bad) —
  increments `live_check_fails`, and once it reaches
  `LIVE_CHECK_FAIL_THRESHOLD` (2), sets
  `live_check_quarantined_until = NOW() + LIVE_CHECK_QUARANTINE_DAYS`
  (3 days). `_claim_promotable()`'s query excludes any genome whose
  quarantine hasn't expired yet — same
  `quarantined_until IS NULL OR quarantined_until < NOW()` shape already
  used by `domain_pool` in `db_local.py::get_domains_for_profile()`, for
  consistency with the one other place this codebase already does
  exactly this kind of thing.
- **Two failures, not one, before quarantine** — a single live-check
  failure could plausibly be a transient network blip unrelated to the
  genome itself (the same class of noise this session already ruled out
  for settle-time, but not impossible in general); requiring a second
  failure before quarantining avoids permanently sidelining a genome
  over a one-off fluke. **Quarantine is time-limited (3 days), not
  permanent** — deliberately, since the whole reason a genome might
  systematically fail live traffic while passing sandbox is the
  documented sandbox/production gap above, which is about the
  *mechanism*, not the specific genome being permanently defective; a
  fixed number is easier to reason about than an ever-growing exclusion
  list, and 3 days is long enough to stop the immediate
  every-cycle-forever churn without permanently writing the genome off
  in case the DPI landscape or a future promotion actually changes the
  outcome.
- **Rollback**: `git revert` this commit plus running
  `ALTER TABLE genome_scores DROP COLUMN live_check_fails, DROP COLUMN
  live_check_quarantined_until;` against the live `z2r_genome` DB fully
  restores prior behavior. Leaving the migration applied but reverting
  only the Python change is also safe — unused columns, no other code
  reads them.
