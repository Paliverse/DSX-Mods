# DSX-Mods

The list of mods that work with [DSX](https://store.steampowered.com/app/1812620/DSX/). DSX shows it under **Installed games > Mods**.
Each mod is one folder in [`mods/`](mods/): a `mod.json` and a cover picture. Changes come in as pull requests; I review
and merge them. **Whatever is merged into `main` is published**: GitHub Actions checks it, builds the catalog and puts it on
<https://paliverse.github.io/DSX-Mods/v1/catalog.json>. DSX reads that file when you open the Mods tab (at most every 6 hours, or
when you choose **Reload mods**) and keeps its built-in list when it is offline.

DSX only links to a mod's page. It never downloads, installs or runs mods.

## Players

- [Request a mod](https://github.com/Paliverse/DSX-Mods/issues/new?template=request-mod.yml): a game you would like a DSX mod for, or a DSX mod that is missing here.
- [Report a listing](https://github.com/Paliverse/DSX-Mods/issues/new?template=report-mod.yml): a broken link, wrong information, or a mod that should not be listed.
- [Removal request](https://github.com/Paliverse/DSX-Mods/issues/new?template=removal-request.yml): you hold the rights to a cover image, game art, logo or text shown here and want it removed.

## Mod authors

- [Submit a mod](https://github.com/Paliverse/DSX-Mods/issues/new?template=submit-mod.yml): fill in the form. Once it is accepted, a pull request with your mod is opened for you.
- [Update my mod](https://github.com/Paliverse/DSX-Mods/issues/new?template=update-mod.yml): change your listing (text, link, cover, features).
- Prefer git? Open a pull request yourself: [CONTRIBUTING.md](CONTRIBUTING.md).
- Building a mod: the [developer kit](kit/) (protocol, JSON schema, examples, a C# client).

## Listing rules

A mod is listed when:

1. **It works with DSX.** The mod sends trigger, light, rumble, haptics, audio or button data to DSX over UDP or the mod pipe (the [developer kit](kit/)).
2. **It is free to download.**
3. **It is posted by its author, or with the author's permission.**
4. **It is hosted on a known mod site**: one of the sites in [tools/allowed-hosts.txt](tools/allowed-hosts.txt) (Nexus Mods, GitHub, Steam, ModDB, BeamNG, GitLab, Codeberg, Race Element). DSX does not show links to other sites. To add a site, ask in an issue.

> **Online games with anti-cheat:** a mod for an online game with anti-cheat may get players banned. DSX lists such mods like any other; the risk is the player's. Authors: say so in the mod's note.

## License

I license only the code and the mod system, under [Apache-2.0](LICENSE) (keep the [NOTICE](NOTICE) file):
the developer kit ([`kit/`](kit/): protocol guide, `DsxModClient.cs`, JSON schema, example packets), the catalog schemas
([`schema/`](schema/)), the catalog tools ([`tools/`](tools/)), the CI and forms ([`.github/`](.github/)) and these docs.

**I don't license the catalog entries.** The text of each entry in [`mods/`](mods/) (title, description, steps)
belongs to the person who submitted it, and each mod keeps its own license. The list exists so DSX can fetch it and show the
mods in the app, and so mod authors can add and update their entries. DSX only links to a mod's page; it never hosts mod files.

**Game names, logos and cover art** belong to their publishers and owners. They are shown only to identify the game a mod is
for; no endorsement by them is implied, and they are not covered by the Apache-2.0 license. Rights holders can ask for removal
with the [removal request form](https://github.com/Paliverse/DSX-Mods/issues/new?template=removal-request.yml); I remove the
image or text promptly, usually the same day.

The DSX name and logo are not licensed; how to say "Works with DSX": [TRADEMARKS.md](TRADEMARKS.md).
