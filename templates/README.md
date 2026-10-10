# Newsletter template

`newsletter.html` is the readable source copy. The packaged runtime copy is
`pubmail/templates/newsletter.html`; keep them identical (tested).

A single column adapts from 680 px desktop to narrow mobile email. HTML uses inline CSS,
presentation tables and locally generated PNG topic tiles for email-client compatibility.
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

Illustrations are deterministic local PNGs: simple outdoors, reading and gaming motifs
selected from topic-title keywords, with an abstract fallback. They are decorative,
not depictions of actual products or evidence about an offer. No remote image fetches,
tracking, generation API, or extra runtime dependency is involved. PNGs are embedded
as CID attachments in email and data URLs in local browser previews.

Both template copies must stay identical. Browser verification does not establish
compatibility in every email client; test delivery separately before enabling schedules.
