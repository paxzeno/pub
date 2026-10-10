# Security model and limitations

This is a conservative mail organiser, not an antivirus or a certified phishing detector.

## Threat boundary
Email and model output are adversarial data. The model cannot execute tools or decide trust.
The application uses separate deterministic checks before any inbox removal or rich rendering.
Only the first Authentication-Results header is considered, and only if its authserv-id is
mx.google.com. Gmail's header handling is part of the trust boundary. Do not reuse this
parser with arbitrary IMAP/imported mail and call those headers trustworthy. Forwarded,
migrated or unusual headers can lack enough evidence and therefore require review.

Aligned DKIM/DMARC demonstrates domain control, not a sender's honesty. A compromised
legitimate account can still send malicious mail. Brand checks cover only configured names;
unknown lookalike brands cannot be automatically recognised. Links are restricted to HTTPS,
no userinfo, no IP literals, standard port, and the sender's registrable domain or exact
configured exceptions. Public suffix parsing uses a packaged list; update dependencies
periodically. Link redirects are NOT followed: a permitted domain can still redirect. The
user must exercise judgement when opening original mail and unsubscribe links.

Alias recognition is exact-domain only. Authenticated relay plus human-reviewed original
sender exceptions are needed to clear forwarding uncertainty. X-Original-From alone is
never an identity proof. No blanket exemption for Proton, SimpleLogin or Apple.

## Render safety
Original HTML supplies text/link evidence and sanitized offline raster previews; it is
never embedded as newsletter HTML. Generated HTML is autoescaped. No scripts, source
attachments or automatic unsubscribe requests. Optional approved CDN artwork is fetched
with public-address pinning, no redirects/cookies/referer, byte/dimension limits and
raster re-encoding. CDN operators may log those requests. Browser networking stays
blocked. Approved header-only unsubscribe controls are separate from ignored trackers. Suspicious entries have
URLs and email addresses defanged to resist email clients' automatic linkification.

## Least privilege
Gmail gmail.modify suffices: no permanent-delete scope needed. The program implements no
trash, delete or read-status operations. Sending uses a separate Himalaya account.
Credential commands are administrator-owned configuration, never email/model supplied.
Remote inference is disabled by default; enabling it discloses selected mail to that provider.
Store directories are 0700, runtime files 0600, umask 077. Backups require equivalent privacy.

## Race and recovery limitations
Gmail provides no compare-and-swap for label changes. We re-read immediately before mutation,
but a read action in the tiny interval between verification and modification cannot be
atomically excluded. No implementation using this API can promise otherwise.

SMTP does not provide exactly-once delivery. An accepted send followed by a lost response
is ambiguous. The durable ledger blocks retries/new sends until an operator checks the
fixed Message-ID in Sent/recipient mail and explicitly reconciles it. Successful CLI send
means SMTP acceptance, not proof of delivery to the recipient. A status of sent means label
completion can resume without another send. Filesystem loss can destroy this protection;
back up state and never erase it casually.

Unsubscribe links can contain recipient-specific identifiers: keep rendered previews private.

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

### Link omission versus email review
`link_policy.omit_same_brand_http: true` discards well-formed HTTP links whose
registrable domain matches the authenticated original sender. It never upgrades,
fetches or renders them. Fragment-only in-page anchors are omitted too. Credentials, unusual ports, malformed separators and
unrelated/lookalike hosts still require review. Set false to restore strict HTTP review.
`link_policy.omitted_service_hosts` maps an exact authenticated original domain to
exact researched or explicitly operator-approved service hosts to discard. Example: `shop.example: [links.mailer.example]`.
This is not a sender allowlist or safe-link allowlist, and cannot establish relay
attribution. No provider-root wildcards; forwarded messages need normal original-sender
verification first. Other links, display-name checks and content classification still
apply. Unknown unrelated domains remain unresolved pending senior investigation;
do not label a mere host mismatch as detected phishing. Research service hosts or obtain explicit operator approval before
adding omissions; never follow recipient-specific tracking or unsubscribe URLs.
A passing link check only permits normal presentation, not automatic mailbox approval.

### Operator-approved tracking-link omission
Distinguish the authenticated From/original-sender domain from a redirect host in
email links. Approval of one domain does not approve a different domain or its
subdomains. When the operator explicitly asks to omit a particular tracking host,
record that exact host under the authenticated original domain in
`link_policy.omitted_service_hosts`. Record the reason and approval provenance in
private deployment notes; do not claim ownership was independently verified.
Recheck the complete message after omission. If all remaining checks pass, clear
the security-review classification for subsequent preparation; do not retain it
solely because of the discarded host. This does not approve redirect destinations,
fetch those links, bypass authentication, change advertising classification, or
create an artwork/unsubscribe allowlist. The Gmail original-message button remains
available even when no sender-provided web links survive.
Keep real sender details and approval records private; public examples are fictional.
Preserve historical sent manifests. Regenerate a preview when requested; clearing a
security flag alone neither resends mail nor archives/newsletter-labels its source.
