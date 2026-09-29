# Vendored static files

Served from `/static/` so the app never reaches a CDN at runtime — phones on the
VPN, a server with flaky upstream, and an offline laptop all get the same page.
To upgrade one, download the new file over the old one and update this table.

| File | Package | Version | Source |
|---|---|---|---|
| `vendor/htmx.min.js` | htmx.org | 2.0.11 | `cdn.jsdelivr.net/npm/htmx.org@2/dist/htmx.min.js` |
| `vendor/alpine.min.js` | alpinejs | 3.17.4 | `cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js` |
| `fonts/barlow-condensed-{600,700}.woff2` | @fontsource/barlow-condensed | 5.3.0 | latin subset — OFL, `fonts/OFL-barlow-condensed.txt` |
| `fonts/public-sans-var.woff2` | @fontsource-variable/public-sans | 5.3.0 | latin subset, variable weight — OFL, `fonts/OFL-public-sans.txt` |
| `fonts/ibm-plex-mono-{400,500}.woff2` | @fontsource/ibm-plex-mono | 5.3.0 | latin subset — OFL, `fonts/OFL-ibm-plex-mono.txt` |
