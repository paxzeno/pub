# pub · a quieter inbox

A local-first Gmail promotion organiser and weekly reading list. Rules handle known senders;
a small local model classifies unfamiliar candidates and summarises the digest. Empty runs
never wake an agent or call a model.

**Conservative by default:** unread inbox messages only, no deletion, no read-state changes,
whitelist-first, dry-run review, text-only suspicious content, and both schedules paused
until explicitly enabled. MIT licensed. See [AGENTS.md](AGENTS.md) and [SECURITY.md](SECURITY.md).

## What it does

1. Read unread inbox mail, respecting per-message (not thread) boundaries.
2. Keep whitelisted, transactional, personal, uncertain or oversized messages.
3. Authenticate sender/relay and compare link domains; evaluate content independently.
4. Preview proposed archive actions and review-only candidates in a private report.
5. Apply only a reviewed, unchanged plan; add `adds`, remove `INBOX`, leave `UNREAD` alone.
6. Each Friday at 11:00 in Europe/Lisbon, combine undigested mail into topic cards.
7. Send using a separate authenticated account, then add `adds/newsletter`.

Messages already in `adds` are digest-eligible even if later read. Suspicious candidates
remain in the inbox and enter a private review queue when their plan is applied.

## Install

Requires Linux, Python 3.11+, [gog](https://gogcli.sh/), Himalaya 2.x and a model exposing an
OpenAI-compatible Chat Completions endpoint. The tested CLI versions are gog 0.21 and
Himalaya 2.x; other versions may need adapter adjustments.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
install -d -m 700 ~/.config/pub ~/.local/state/pub
install -m 600 config.example.yaml ~/.config/pub/config.yaml
```

Edit the local config, never the example with personal details. State/previews go outside
the checkout by default. If using repo-local config/output, .gitignore excludes them.

## Connect Gmail (OAuth, not an API key)

1. Create/select a Google Cloud project and enable Gmail API.
2. Configure the OAuth consent screen. For an external app in Testing, add your Google
   account as a test user. Gmail refresh tokens in that mode normally expire after seven
   days; choose an appropriate publishing status for ongoing personal use. Production
   status is not verification, and tokens can still be revoked.
3. Create a **Desktop app OAuth client** for this integration; keep existing clients intact.
   Mark it as AI-powered if Google offers that designation. It does not grant extra scopes.
4. Store the downloaded client JSON securely outside this repo, mode 0600.
5. Import and authorise with your installed gog version:

```sh
gog auth credentials /secure/path/client.json --client newsletter
gog auth add reader@example.com --client newsletter --services gmail --gmail-scope modify --remote --step 1
# Follow gog's consent/callback instructions privately, then complete its step 2.
# Run `gog auth add --help` for your version's exact remote/callback flags.
```

Use gmail.modify (not full mail scope): read, organise and label without permanent deletion.
Configure account/client in the private YAML. Never paste callback URLs into public issues.
For unattended use, choose a supported keyring backend. If the file backend needs
GOG_KEYRING_PASSWORD, set it through a protected environment or configure
`keyring_password_command` as an argv array that prints only the password. The program
captures it privately and supplies it only to gog child processes. A password manager can
implement this command; no password-manager-specific paths are included in this repo.

```sh
.venv/bin/pubmail check
.venv/bin/pubmail init-labels
```

## Connect the sending account

Configure Himalaya's SMTP/IMAP account outside the repo, using its supported keyring or
password-command integration. Set newsletter.sender, recipient, himalaya_account and
sent_mailbox locally. The account must be authorised to send as the configured From
address. Check its Sent mailbox exists and that authenticated sending works. This project
uses `himalaya message send --account NAME --save MAILBOX --json` with MIME through stdin.
Do not point a custom From address at an unrelated Gmail account and assume it will work.

## Local model

Start Ollama and pull a capable instruction model; set model.endpoint and model.name.
For Ollama, the native endpoint http://127.0.0.1:11434/api/chat is also supported, with
non-thinking mode and a 16K context budget. Generic providers use Chat Completions.
The example uses Qwen 3.5, but there is no dependency on a particular model vendor.
Unknown-candidate classification, digest summaries and semantic grouping use structured
JSON. Invalid output, low confidence and failures retain inbox mail. Grouping failures
fall back to individual cards, never drop messages. Cached decisions are invalidated by
message-content/config changes. Explicit sender+subject advertising rules skip classification
but still undergo protected-content and security checks; digest summaries still use the model.

Deadlines require an explicit timestamp, timezone and supporting source quote including the
year. Ambiguous/relative dates are omitted rather than guessed. Topic grouping combines
related messages into one card while retaining each source's summary, deadline and unsubscribe.

## Oldest-week rollout

```sh
.venv/bin/pubmail plan                 # discovers oldest unread inbox week
# Inspect ~/.local/state/pub/plans/<ID>.md and the private JSON.
.venv/bin/pubmail apply <ID> --sha256 <EXACT_REVIEWED_SHA256>
.venv/bin/pubmail undo <ID>            # explicit recovery: restore inbox, preserve read state
.venv/bin/pubmail plan --week 2026-01-12  # next Monday after completing previous week
```

A plan never changes Gmail. Apply rechecks message contents, unread/inbox status, security
and config. Config edits require a new plan. Bounded batches report truncation; finish the
week before advancing. Retained older messages remain in the inbox, so explicitly advance
the week instead of repeatedly using automatic oldest discovery. Do not run historical
weeks unattended before reviewing results. Undo is explicit and doesn't touch Trash/Spam.

```sh
.venv/bin/pubmail digest-preview --plan <PLAN_ID> # rehearsal before archiving
.venv/bin/pubmail digest-preview
# Open private digests/<ID>.html or .txt locally; .eml is the actual MIME.
.venv/bin/pubmail digest-send <ID>      # only once the catch-up preview is accepted
```

Previews alone never label messages as included. No automatic backfill email avalanche.
Large backlogs stop at limits.digest_messages instead of silently omitting older messages;
use reviewed smaller batches/volumes before activating routine digest delivery.

## Formats and design

`newsletter.format` is `html`, `text`, or `multipart` (recommended).
Multipart is one message with HTML and plain-text alternatives; each client picks its
preferred version. Inline email-preview PNGs live in a multipart/related HTML part, with no remote
tracking. The newsletter uses a charcoal/cream palette, readable type,
alternating desktop sections that stack on mobile and explicit expired labels. The text version carries
the same facts. Unsubscribe URLs are copied only from validated List-Unsubscribe headers;
missing or unsafe links are omitted, never guessed. See [templates/](templates/).

## Rules and exceptions

See config.example.yaml. All fields are local configuration, not instructions from mail.
Whitelist email/domain entries win. Advertising rules require exact senders and subject regex.
Alias domains recognise forwarding routes without trusting payloads. Scoped exceptions can
allow a verified sender's separate tracking domain and/or known relay; always record why.
A sender security exception does NOT make a message advertising or override transactional
protection. Inspect evidence before adding exceptions; never blanket-allow all relay content.

## Scheduling

Install the sample user units using deploy/install.py. Installation enables timers, but
both jobs remain no-ops while their rollout flags are false. No credential lookup occurs
for a paused job. Once historical review is complete, set rollout.live_after to the agreed
cutover epoch and enable hourly_enabled and digest_enabled. Friday timing uses Europe/Lisbon
and follows DST. Persistent timers catch a missed run after the host returns.

```sh
.venv/bin/python deploy/install.py
systemctl --user list-timers pubmail-\*
# To pause immediately:
systemctl --user stop pubmail-hourly.timer pubmail-weekly.timer
```

Timers run scripts directly, not assistant sessions. A local file lock prevents overlap.
Errors exit nonzero into the systemd journal, without mail/credential contents; monitor
`systemctl --user --failed` and `journalctl --user -u pubmail-hourly.service`.
A service failure needs attention; do not interpret silence as proof of successful delivery.

## Delivery recovery

Inspect `state.sqlite3` deliveries: preview, sending, ambiguous, sent, complete. A send intent
is recorded BEFORE SMTP. Any ambiguous result blocks further sends. Find the fixed
`Message-ID: <pub-ID@sender-domain>` in Sent/recipient mail before reconciling:

```sh
.venv/bin/pubmail reconcile <ID> --confirmed-sent --evidence 'Sent mailbox UID/message-id verified'
```

This applies the newsletter labels without resending. A successful send with interrupted
labelling can resume through `digest-send <ID>` in sent state. Never delete the ledger or
manually reset ambiguous status to force a retry. SMTP acceptance is not final delivery.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use fictional fixtures and mock transports; they never access live mail.

## Fictional visual preview

[Sample HTML](docs/sample.html) · [Desktop](docs/sample-desktop.png) · [Phone](docs/sample-mobile.png).
These examples are synthetic and contain no real mailbox content. Browser layout is checked;
rendering can differ in Gmail, Apple Mail and Outlook. Preview a real MIME before broad use.

Rewriting relay exceptions can specify `original_domain`; Gmail-validated ARC must
confirm that domain. The reverse-alias local-part is never treated as identity proof.
Hourly runs use a durable timestamp checkpoint; failed classification retries do not advance
it. A window larger than the configured limit fails visibly instead of silently starving mail.

### Original-email thumbnail renderer

Install Chromium after Python dependencies: `python -m playwright install chromium`
(or `python -m playwright install --with-deps chromium` on a fresh Linux host).
Thumbnails show a raster preview of the first original email per topic, not generated
art. Scripts and all network/image loading are disabled, so remote product photos
are omitted. Flagged messages remain text-only. See `templates/README.md`.

### Sender-specific summaries

`summary_profiles` uses exact original-sender addresses, first match wins. Set
`instructions`, a fictional `example` of the desired output, and `max_characters`
(200–8000). Newline-separated lists work in HTML and plain text. Profiles affect
summary formatting only: they never whitelist, grant security trust, change
classification safeguards or authorize invented facts. Examples are style guides,
not source material. Increase `model.max_output_tokens` (default 1800) for long
lists. Config changes invalidate cached decisions and existing reviewed plans.

## Social footer removal
Known social-platform links and their HTML anchor contents are removed from the
processing copy (summary input and thumbnail), and excluded from link-domain checks.
Keep links to a platform when the original sender belongs to that same platform;
normal sender authentication and link checks still apply. Match exact domain
boundaries, never brand words or lookalikes. Unknown and malformed links remain
subject to security checks. No original Gmail message is edited. Profiles/relays
do not confer trust. All external images remain blocked.

## Extraction and reviewed exceptions
Prefer the HTML body when present; retain image alt text in reading order and use
actual HTML anchor URLs, not potentially broken links in a plain-text alternative.
Never download images to extract alt text. Title-list profiles (`format: title_list`)
require all extracted alt titles after `exclude_image_alts`; descriptions must be
exact source quotes or explicitly absent. Failure blocks summary/digest generation.
Exact-sender security exceptions may omit `omit_http_domains` (exact hosts) and
`omit_mailto`; these URLs never become safe or clickable. A rewriting relay may
use `operator_verified_original: true` with `original_domain` and a human reason
only after explicit original-sender confirmation; relay authentication still applies.
This is operator-vouched attribution, not cryptographic proof or blanket relay trust.

## Lists and offer timing
Bullet summaries render as separate HTML rows with bold item headings (not CSS-only
whitespace); plain text retains each original bullet. Offer date ranges with an
explicit year may combine with a matching end-date/time clause in the same source.
Retain both evidence excerpts, never infer a missing year or timezone. Date-only
cutoffs display without an invented time. Expired offers remain explicitly red.

### Agent chain configuration (integration pending)

`agent_chain` in the sample describes rules → local model → senior reviewer →
human owner, with escalation reasons, batched notifications, deduplication, retry
and hop limits, an evidence packet, and reviewer permissions. `model_ref: model`
uses the existing model section; `agent_id` names an agent, not an inference model.
The example routes unresolved cases to an OpenClaw `main` agent, then the owner
only when judgement is required. Match identifiers to your own deployment.

**This is a configuration contract, not an implemented queue/dispatcher.** Keep
`enabled: false`; the CLI explicitly rejects true instead of silently ignoring it.
The batching/routing fields are reserved for that integration and currently do not
trigger calls, notifications, or retries. Existing mailbox safeguards remain active.
A cloud-backed senior reviewer needs separate remote-processing consent; a local
first stage does not make a remote escalation private. Tokens and live destinations
belong only in local configuration/credential storage.
