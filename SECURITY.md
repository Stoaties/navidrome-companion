# Security Policy

navidrome-companion is a **self-hosted** application: you run it on your own
hardware and are responsible for how it's exposed. This policy covers
vulnerabilities in the project's own code and its default configuration.

## Reporting a vulnerability

**Please do not report security issues in public GitHub issues.**

Instead, report privately using one of:

- GitHub's [private vulnerability reporting](https://github.com/Stoaties/navidrome-companion/security/advisories/new)
  (**Security → Report a vulnerability**), or
- Email **corentin.gouanvic@gmail.com** with the details.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof of concept if you have one).
- The affected version / commit and your deployment setup.

This is a hobby project maintained in spare time, so please allow a reasonable
window for a response before any public disclosure. Fixes will be released as
soon as practical, and reporters will be credited unless they prefer to remain
anonymous.

## Supported versions

Only the latest `main` is supported. There are no long-term release branches;
please update to the current version before reporting.

## Hardening notes (your responsibility)

Because this is self-hosted, most of your security posture is in your hands:

- **Change the default admin password immediately.** It is intentionally static
  (`admin` / `changeme`) so first login is frictionless, which means it is
  public knowledge. The app forces a password change on first login — complete
  it.
- **Only expose ports 80/443.** Navidrome and the companion are meant to be
  reached through Caddy, never published directly.
- **Caddy's admin API** is bound to the internal Docker network and must not be
  exposed to the host or the internet.
- **Keep dependencies current** — especially `yt-dlp` (installed in the image)
  and the base images, which change often.
- Treat any Spotify API credentials you add in Settings as secrets.

## Scope

In scope: authentication/session handling, the download/import job workers,
config rendering to Caddy, and anything that could let an unauthenticated user
reach the app or the host.

Out of scope: vulnerabilities in upstream projects (report those to
[Navidrome](https://github.com/navidrome/navidrome),
[yt-dlp](https://github.com/yt-dlp/yt-dlp), [Caddy](https://github.com/caddyserver/caddy),
etc.), and issues that require an already-privileged/authenticated admin.
