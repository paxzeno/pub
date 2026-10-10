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
44 px action targets. Thumbnail and topic count sit above the text, never beside
the whole summary. At 520 px and below, gutters shrink and action links stack.
Inline defaults remain readable when a client strips media queries. Desktop width
is capped at 680 px to keep line lengths comfortable.

Visual direction: an editorial charcoal masthead, restrained lime accents, numbered
topic headers, bold sans-serif titles and pill-shaped primary actions. The review
section uses its own amber treatment; expired deadlines retain explicit red labels.
All essential styling stays inline; no web fonts, external images or CSS dependencies.
The opening topic has a light accent panel, followed by quieter white supporting
items. This is visual hierarchy, not an inferred importance ranking.
