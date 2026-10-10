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
All original HTML is parsed only for plain text and link evidence, then discarded. HTML
output is autoescaped. No remote images, scripts, attachments, embedded source HTML or
automatic unsubscribe requests. Thumbnails are generated locally. Suspicious entries have
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
