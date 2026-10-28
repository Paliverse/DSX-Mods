# Security

Report a malicious, hijacked or impersonating listing privately:
[open a security advisory](https://github.com/Paliverse/DSX-Mods/security/advisories/new). For everything else, use the
[report form](https://github.com/Paliverse/DSX-Mods/issues/new?template=report-mod.yml).

What to include: the mod's id (its folder in `mods/`), what is wrong, and how you found out.

What happens: a harmful listing is removed the same day it is confirmed (a deletion merged into `main` is published at once,
and DSX drops it the next time it reads the catalog). DSX never downloads or runs mods; it shows links to sites that check
their uploads (Nexus Mods, GitHub, Steam, ...), and only to the sites in `tools/allowed-hosts.txt`.
