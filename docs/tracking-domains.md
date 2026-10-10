# Research-backed tracking exclusions

Reviewed 2026-10-10. This is a curated starter set for widely used email providers,
not an exhaustive registry or a popularity ranking. Exclusions REMOVE destinations;
they never declare the sender, message or redirect target safe. No redirect is fetched.

## Enabled

- **SendGrid:** subdomains of `ct.sendgrid.net` (such as account-specific `u…` hosts).
  [Twilio support](https://help.twilio.com/articles/50688232632475) documents the click URL form.
  [Link branding](https://www.twilio.com/docs/sendgrid/ui/account-and-settings/how-to-set-up-link-branding)
  explains shared versus customer-branded domains. Not all of `sendgrid.net`.
- **Constant Contact:** exact `r20.rs6.net`.
  [Staff explanation](https://community.constantcontact.com/t5/Product-Ideas/Turn-off-link-tracking-in-campaigns/idi-p/334097)
  identifies intermediate click-reporting URLs.
  [Provider domain list](https://knowledgebase.constantcontact.com/email-digital-marketing/articles/KnowledgeBase/5800-Safelist-Constant-Contact-web-domains-in-a-security-program?lang=en_US)
  corroborates the service domain. Not every domain on that general safelist is a tracker.
- **Amazon SES:** subdomains of `awstrack.me`.
  [AWS documentation](https://docs.aws.amazon.com/ses/latest/dg/configure-custom-open-click-domains.html)
  documents regional tracking hosts such as `r.us-east-1.awstrack.me`.
- **Existing operator-approved exclusions:** exact `ctrk.klclick.com`,
  `ctrk.klclick1.com`, `manage.kmail-lists.com`. These were approved based on observed
  email routes; they were NOT newly verified by this research. Klaviyo's
  [shared/custom tracking guide](https://help.klaviyo.com/hc/en-us/articles/360001550572)
  explains the mechanism but the searched documentation did not name these exact hosts.
  The last host is subscription management, not purely click tracking.

## Investigated but not broadly excluded

- **Mailchimp:** `mailchi.mp` hosts campaign pages and landing pages; removing all
  links would remove actual content. `list-manage.com` also hosts signup forms.
  [Email URLs](https://mailchimp.com/help/email-urls/),
  [landing pages](https://mailchimp.com/help/landing-page-urls/),
  [click tracking](https://mailchimp.com/help/enable-and-view-click-tracking/).
- **HubSpot:** official docs establish click tracking, but the searched sources did
  not establish exact ownership/purpose for `hs-links.com` or `hs-cta.net`.
  [Provider documentation](https://knowledge.hubspot.com/marketing-email/manage-marketing-email-open-and-click-tracking).
  Do not add guessed domains or all of hubspot.com.
- **Mailgun:** tracking hosts are often `email.mg.<customer domain>` CNAMEs.
  [DNS setup documentation](https://help.mailgun.com/hc/en-us/articles/15353034939931-GoDaddy-DNS-Setup-Guide).
  A hostname containing `email.mg` is not proof of provider ownership. No heuristic exclusion.

- **Brevo:** [provider IP/domain documentation](https://help.brevo.com/hc/en-us/articles/208848409-Brevo-IP-ranges-improve-the-deliverability-of-B2B-emails)
  associates `sendibt2.com` and `sendibt3.com` with the service but does not establish
  a tracking-only role. Not automatically excluded.
- **Campaign Monitor:** [custom-domain documentation](https://help.campaignmonitor.com/articles/Knowledge/custom-domain-names)
  describes customer `createsend.com` domains, not a confirmed tracking-only suffix.
  No exact official documentation for `createsend1.com` was found; not added.

## Matching contract

`ignored_tracking_domains` matches exact HTTPS hosts. `ignored_tracking_domain_suffixes`
only matches strict subdomains at a dot boundary: `u123.ct.sendgrid.net` matches,
`ct.sendgrid.net.evil.example` and `evilct.sendgrid.net` do not. Root domains do not
match the suffix rule. Userinfo, malformed URLs and unusual ports are never exempted.
Remaining links and sender/relay authentication still undergo normal checks.
Provider changes should be researched before expanding this list. Never automatically
promote a model guess into persistent trust or treat a tracker as a safe redirect.
