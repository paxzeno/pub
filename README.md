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
Thumbnails show a raster preview of the first original email per sender, not generated
art. Scripts and browser networking are disabled. Optional approved artwork is
fetched separately, cached and re-encoded before offline rendering. Flagged messages remain text-only. See `templates/README.md`.

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
do not confer trust. Only separately approved cached raster artwork can be embedded; browser networking remains blocked.

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
Bullet summaries render as separate paragraphs with inline bullet markers and bold
item headings (not CSS-only whitespace); plain text retains each original bullet. Offer date ranges with an
explicit year may combine with a matching end-date/time clause in the same source.
Retain both evidence excerpts, never infer a missing year or timezone. Date-only
cutoffs display without an invented time. Expired offers remain explicitly red.

### Bring your own senior reviewer

`agent_chain` routes rules → local model → senior reviewer → owner. It is optional
and disabled in the public sample. The implementation uses a provider-neutral
`command_json` adapter: configured argv receives one JSON request on stdin and
returns one JSON response on stdout. OpenClaw is an optional bundled adapter,
not a dependency of the core handoff. See **AGENTS.md → BYO reviewer setup** for
connection, credentials, protocol and operational instructions.

Uncertain triage decisions are batched at the end of a scan. Model/extraction failures
and invalid digest grouping also request review (single-task batches). Responses
pass the same classification, title coverage, deadline and grouping validators as
local output. A senior cannot bypass protected content, sender authentication,
link checks or the existing archive-plan checkpoint. It cannot update trust rules.

Persistent SQLite review state deduplicates identical task+policy payloads. Batch
size, minimum interval and rolling-24-hour budget are enforced. No work means no
invocation. Quota-limited pending cases resume when that input is processed again;
there is no independent background dispatcher. Failed, ambiguous, deferred and
owner-needed cases do not automatically retry. Review their status using:

```sh
pubmail --config ~/.config/pub/config.yaml review-status
pubmail --config ~/.config/pub/config.yaml review-test
```

`review-test` forces a local-model failure on a fictional receipt, exercises the
real adapter in an isolated temporary state directory, validates the response,
and makes no mailbox calls. It consumes one real reviewer invocation.

The owner queue is local, visible in status and the private SQLite `senior_items`
table; it does not send unsolicited owner notifications. Inputs exceeding the
configured excerpt bound remain unresolved instead of sending partial evidence.
A local command can still use a cloud model: declare `processing: remote` and
explicitly opt in with `review_packet.allow_remote_processing: true`.

The routing diagram/permission fields document the fixed chain in this version;
it is not an arbitrary multi-hop workflow engine. One senior attempt per task
and two hops are supported. Enabled adapters do not enable either mail schedule.
Credentials, source mail, responses and private destinations must remain local.

### Reviewer cooldown

Set `agent_chain.batching.min_interval_minutes` to an integer from **0 to 720**
(12 hours). `0` dispatches eligible pending work without a cooldown; `60` waits
one hour between batches. The same configured delay applies to manual and scheduled
runs. Batch-size limits, the rolling daily budget, and deduplication still apply
when the cooldown is zero. Changing this value does not start a run or enable timers.

```yaml
agent_chain:
  batching:
    min_interval_minutes: 0  # Immediate dispatch during supervised cleanup
```

This is a partial example: retain the other agent-chain settings.

Original-message buttons use account-scoped Gmail `rfc822msgid:` search when the
source Message-ID is available; legacy records fall back to thread IDs, not message
IDs. Review diagnostics name sender/relay domains and every differing HTTPS host,
never recipient-specific URL paths/tokens. Known forwarding is not itself a link
mismatch. Domain details in review sections remain defanged and non-clickable.

### Ignored marketing-service links
`ignored_tracking_domains` lists exact HTTPS hosts to discard from link checks and
returned safe/unsubscribe URLs. It is NOT a trust allowlist: never render those
destinations as clickable newsletter links or fetch their redirect targets. Keep
useful anchor text; the offline thumbnail already strips navigation and blocks
network requests. Sender/relay authentication and every other link remain checked.
No wildcard matching, automatic trust inference or automatic unsubscribe.

Research-backed common tracker exclusions and sources are in
[docs/tracking-domains.md](docs/tracking-domains.md). Use exact hosts normally;
`ignored_tracking_domain_suffixes` supports strict subdomains of documented
tracking-only infrastructure. This explicit suffix field does not accept substring
or wildcard patterns, and must never contain general hosting/provider roots.

Newsletter layout uses one thumbnail/card per exact verified original sender.
Different campaigns retain separate headings, summaries, timing and original links
within that card. Topic grouping controls ordering, not sender-card boundaries.
Flagged messages remain in the separate text-only review section.

### Optional artwork and unsubscribe controls
`image_loading` selectively fetches approved raster artwork into a private cache;
the screenshot browser remains offline. The sample is disabled by default. See
AGENTS.md for bounds and privacy tradeoffs. This loader alone does not perform OCR; enable the separate `vision` step below
to add image evidence to model summaries. `unsubscribe_controls` preserves approved
header-only subscription links independently of discarded click trackers; no
unsubscribe request is executed automatically.

### Choosing a model for image understanding
Choose the **installed model and serving backend** by supported input types, not
by vendor name. Image-heavy newsletters need OCR/text reading AND visual recognition.
A text-only model can summarise extracted text but cannot read a poster it never sees.

For a local Ollama deployment, `qwen3.5:latest` is a working candidate: the tested
9.7B Q4_K_M installation reports `vision`, and a real poster-reading probe succeeded.
Tags can change: verify your own installed version, then pin it for repeatability.
The inspected `nemotron-3-nano:4b` and its invoice-specific attachment derivative
reported text capabilities, not vision. This is not a claim about every NVIDIA model;
a different NVIDIA vision model/backend may be suitable after the same checks.

Check local metadata (no email content is sent):
```sh
curl -s http://127.0.0.1:11434/api/show \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:latest"}'
```
Require `vision` in `capabilities`, then test with a non-sensitive image containing
known text. Check titles, small print and dates, not only broad image descriptions.
The same vision model may handle text tasks, or `vision.model` can select a dedicated
image extractor while `model` remains the text summariser. No particular vendor is required.

Existing model selection uses these **supported** YAML keys:
```yaml
model:
  endpoint: http://127.0.0.1:11434/api/chat
  name: qwen3.5:latest
  allow_remote: false
  timeout_seconds: 180
  max_output_tokens: 1800
```
This is a partial example; retain other config sections. `image_loading.enabled`
controls approved artwork fetching, not model vision. Enable structured extraction separately:
```yaml
vision:
  enabled: true
  model: {}  # Inherit model; optionally override name/endpoint/timeout here.
```
Use the mapping shown, not a bare `vision: true`.

**Integration status:** image-aware extraction now passes approved cached image
bytes through native Ollama `messages[].images` or OpenAI-compatible image content.
It reads each source separately, caches structured evidence by image/model/contract,
and merges visual text with HTML/alt text before summaries. Title-list profiles
include visual titles. Invalid/unreadable evidence, missing approved assets and
exhausted per-pass budgets stop generation with saved progress rather than silently
produce a complete-looking digest. Rerun the same input to resume. The model can still misread stylised text;
JSON/source-association checks are not proof of visual accuracy. The text-only
senior adapter does not receive image bytes and cannot repair unread artwork.
See [AGENTS.md](AGENTS.md#required-vision-extraction-pipeline) for the contract.

Keep image inference local by default. A remote backend requires explicit remote
processing consent and appropriate authentication; approved image downloads do not
authorise uploading email artwork to an unrelated service. Never send image-only
content to a text-only fallback while claiming it received equivalent evidence.

### Processing cost
Rules and text-only triage run before expensive visual extraction. Digest preparation
reads candidate artwork using the image/evidence caches. Sender presentation grouping
is deterministic and makes no model call. Pubmail inference is serialised across its
processes using a shared state-directory lock; other host workloads are not throttled.

### Resumable image work
There is no 12-image ceiling. Each source is processed serially in bounded passes:
```yaml
image_loading:
  downloads_per_pass: 16  # New downloads; cached artwork does not consume this budget.
vision:
  images_per_pass: 4     # New image extractions, each with at most one validation retry.
  pass_seconds: 120      # Soft budget checked before starting another image.
```
Keep existing enabled/hosts/model settings. Limits must be positive integers (downloads
1–256, images 1–128, seconds 1–3600). A model call already in progress can exceed the
soft pass duration; its configured timeout still applies. Validated evidence is saved
after every image. Cache keys include image bytes, model configuration and extraction
contract, not processing budgets. Restart the same preview to consume the next pass;
already validated images require no inference. No partial summary or send is permitted.
`ProcessingPending` is resumable; unreadable images and failed downloads are real errors,
not automatic-retry instructions. Scheduling remains unchanged. Never retry ambiguous
senior-agent or SMTP attempts as a side effect of resuming image work.

The CLI exits **75** for pending image work (resume the same command), and **1**
for an actual failure. Do not treat every nonzero exit as permission to retry.
Plan previews now regenerate normal-item summaries with visual evidence; their
private JSON retains source evidence for inspection, but creates no delivery or labels.

Single-day events with an explicit source year also receive event badges. Keep
raw ambiguous event dates and urgency visible without guessing a cutoff/year.

### Contact and bare-website links
After sender/relay authentication, omit `mailto:` contact actions instead of treating
these as unsupported web destinations. Never render them as newsletter links or
unsubscribe controls. Bare ASCII website addresses with no scheme may be omitted
only if their registrable domain matches the authenticated original sender domain;
never add a scheme, fetch, follow or turn them into clickable URLs. Credentials,
ports, backslashes, lookalikes and unrelated bare hosts do not inherit this rule.
Other malformed/non-HTTPS links remain subject to review; diagnostics identify the
scheme/host without recipient-specific paths or tokens. These are link omissions,
not sender trust exceptions or advertising-classification approvals.

Plan previews recheck link security against current rules for both normal and
review candidates. Passing candidates can receive rich presentation; this does
not edit the stored plan, approve archiving or set newsletter-delivered labels.

Explicit single-date “Offer ends/expires Month Day, Year” cutoffs also get
EXPIRED/deadline badges, including cached summaries. Date-only extraction does
not invent a time; retain any source-stated time in the summary/original.

### Inline image identity
Bind Content-ID and image filename to the MIME message ID, source message ID and
image-byte hash. Never reuse positional IDs such as topic-0 across newsletters:
mail clients may reuse cached inline parts when card order changes. Every HTML cid
reference must resolve to exactly one attached image in that message. Verify source
association, not only attachment counts. A browser preview alone cannot prove a mail
client will display the newly transmitted image.

Keep inline Content-ID values short ASCII msg-ids (128-bit content-derived identifiers), so the complete header stays below the SMTP folding limit. Verify serialized RFC 5322 bytes contain a literal angle-bracket Content-ID, never RFC 2047 encoded words. Decoded attachment metadata alone can hide a broken wire header. Check both Sent and received copies when diagnosing rendering failures.

### Calibration without review quotas
Set `agent_chain.batching.enforce_limits: false` to bypass the configured daily review quota and cooldown without deleting their values. Missing switch defaults to true for existing installations. Agree on operational quotas with the owner after calibration; do not silently re-enable them. Batch size and resumable image-pass sizes remain work chunking, not daily quotas. Connection timeouts, payload-size constraints, authentication, validation, serial inference and ambiguous-attempt/delivery deduplication remain active. Toggling enforcement preserves reviewer identities and never resets attempts or automatically retries ambiguous work.

### Investigate forwarded attribution before escalating
Recognise `X-SimpleLogin-Original-From` and `X-Original-From` only as original-sender hints. For a configured relay, require its aligned authentication plus matching original-domain DMARC evidence within the first Gmail Authentication-Results validated ARC-pass summary. Never trust raw sender-supplied ARC headers, decode alias local-parts as identity proof, or infer trust from a forwarding service alone. Conflicting/duplicate original-sender headers fail closed. Successful attribution still passes all ordinary link and impersonation checks; it does not grant blanket sender exceptions. Before presenting an attribution warning, inspect the available authentication/header evidence and compare any directly authenticated copy. Identical bodies are corroboration, not an authentication substitute. Report the actual missing or conflicting evidence. Explain retry selection versus total backlog; a small retry is not a complete week scan.

Every source entry, including review items, shows `From: address` then `Date: yyyy-mm-dd hh:mm:ss` on the next line in both HTML and plain text. Use the source Gmail receipt timestamp in the configured timezone; do not substitute digest-generation time. Sender grouping preserves each source timestamp.

Approved static-artwork paths may contain `%20` spaces. Other percent escapes, encoded separators/traversal, literal `..`, redirects and unapproved hosts/paths remain rejected. This is filename compatibility, not a broader CDN trust rule.

Vision inputs smaller than 64 pixels on either axis are padded without rescaling or changing their source-image hash; this avoids Qwen image-processor errors on small logos. `image_loading.max_download_bytes` controls each approved asset download (default 3000000, maximum supported 50000000), independently of usage quotas. GIF loading currently extracts the first frame only; do not claim all animation frames were inspected.
