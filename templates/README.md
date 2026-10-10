# Newsletter template

`newsletter.html` is the readable source copy. The packaged runtime copy is
`pubmail/templates/newsletter.html`; keep them identical (tested).

A single column adapts from 680 px desktop to narrow mobile email. HTML uses inline CSS,
presentation tables and local PNG email screenshots for email-client compatibility.
No original HTML or tracking images are inserted. Jinja autoescapes every text field.
Plain text is rendered from the same data in pubmail/digest.py, not stripped from HTML.
Fictional previews can be generated with `python examples/preview.py` after installation.
Generated private mail, previews and MIME must never be committed.

Readability: full-width 17 px summaries, 14 px source/deadline details, and at least
44 px action targets. Desktop width is capped at 680 px. At 520 px and below,
illustrations and headings stack and actions become full-width.

Composition: a full-width opening illustration, then alternating illustration/heading
rows with summaries below. Open white sections and fine rules replace repeated cards.
The review desk remains visually distinct, text-only, and without active links.

Thumbnails are raster screenshots of the first original email in each topic group,
not generated artwork. Original HTML is sanitized and rendered in offline Chromium
with JavaScript disabled, all network requests aborted, and a restrictive CSP.
Images (including tracking pixels), frames, forms and navigation are blocked.
Remote product photos therefore do not appear. Text-only mail gets a plain-text
screenshot. Older cached plans without HTML also fall back to their original text.
Only PNGs enter the newsletter, never original HTML. Flagged items are never rendered.
Install the browser with `python -m playwright install chromium` (Linux hosts may
need `python -m playwright install --with-deps chromium`). Renderer failure prevents
sending rather than substituting invented artwork. Public samples use fictional
source emails; real source HTML and screenshots must remain private.

Both template copies must stay identical. Browser verification does not establish
compatibility in every email client; test delivery separately before enabling schedules.
