# Contributing

Most authors use the forms ([submit](https://github.com/Paliverse/DSX-Mods/issues/new?template=submit-mod.yml), [update](https://github.com/Paliverse/DSX-Mods/issues/new?template=update-mod.yml)); this page is for pull requests.

## One mod, one folder, one pull request

```
mods/<id>/mod.json
mods/<id>/cover.jpg        (or .png, .webp, .avif; optional, at least 320x180, at most 10 MB)
```

`<id>` is 3-48 characters of `a-z`, `0-9` and `-` (for example `wf2-dsx`). Nothing else goes in the folder. The cover is cut to
16:9 around its centre and saved as a 1280x720 JPEG when the catalog is built, so any reasonable picture works.

## mod.json

```json
{
  "$schema": "../../schema/mod.v1.schema.json",
  "name": "WF2_DSX",
  "author": { "name": "SYSTEMATI0N", "url": "https://github.com/SYSTEMATI0N" },
  "maintainers": ["SYSTEMATI0N"],
  "games": [{ "name": "Wreckfest 2", "steam_app_id": null, "aliases": [] }],
  "summary": "Adaptive triggers and light bar for Wreckfest 2.",
  "description": "Plain text, up to 2000 characters. Line breaks are kept; HTML and Markdown are shown as typed.",
  "note": "Optional: one requirement or limit.",
  "links": { "home": "https://github.com/SYSTEMATI0N/WF2_DSX", "source": "https://github.com/SYSTEMATI0N/WF2_DSX" },
  "features": ["triggers", "lights"],
  "transports": ["udp"],
  "mod_ids": ["wf2-dsx"],
  "requires": { "dsx": "3.1" },
  "status": "listed"
}
```

| Field | Rule |
|---|---|
| `name` | Required, at most 80 characters, one line. |
| `author.name` | Required, at most 60 characters, without `@` (DSX shows `@name`). `author.url` optional. |
| `maintainers` | GitHub accounts allowed to change this entry later. |
| `games` | 1-10 games. `name` is what stores call the game: DSX matches installed games by name (case, ™, ® and colons ignored) and, for Steam, by `steam_app_id`. |
| `summary` | Required, at most 100 characters, one line: what the mod does. |
| `description` | Required, at most 2000 characters, plain text. |
| `note` | Optional, at most 160 characters, one line. |
| `links.home` | Required: the mod's page. `links.source` optional. https only, on a site in [tools/allowed-hosts.txt](tools/allowed-hosts.txt). |
| `features` | One or more of `triggers`, `lights`, `rumble`, `haptics`, `audio`, `remap`. |
| `transports` | `udp` and/or `pipe`: how the mod talks to DSX. |
| `mod_ids` | Optional: the `ModId` values the mod sends (1-64 of `A-Z a-z 0-9 . _ -`), unique in the catalog. |
| `requires.dsx` | Optional: the oldest DSX version the mod works with. Older DSX versions hide the mod. |
| `status` | `listed`, or `deprecated` (needs a `reason`; DSX hides deprecated mods today). |

No download, installer or file fields: DSX links to the mod's page and nothing else.

## Checks

Every pull request runs [validate](.github/workflows/validate.yml): the rules above, the cover, the links of the changed mods,
and a summary of what changes ("adds wf2-dsx", "LINK CHANGE: changes links.home of ..."). Run them yourself with Python 3.12:

```
python -m pip install --require-hashes -r tools/requirements.txt
python tools/catalog.py validate
python tools/catalog.py diff origin/main
```

## Review

I review every pull request (aim: an answer within 7 days). A change of a link on someone else's mod needs the author's
confirmation. The [listing rules](README.md#listing-rules) apply. Once merged, the change is live within minutes and reaches DSX
the next time the Mods tab is opened after 6 hours, or on **Reload mods**.

## Rights

- **Code** (kit, schemas, tools, workflows): contributions are under [Apache-2.0](LICENSE), the same as the rest of the code
  (Apache-2.0 section 5).
- **Your entry** (title, description, steps, and a cover you made): stays yours; I don't license it. By submitting
  it you confirm: "I have the right to submit this text and image, and I'm OK with DSX showing them in the app and in this
  repository."
- **Your mod** keeps its own license. The catalog only links to it and never hosts it.
- **Game names, logos and cover art** belong to their publishers and owners and are shown only to identify the game. A rights
  holder can ask for removal with the [removal request form](https://github.com/Paliverse/DSX-Mods/issues/new?template=removal-request.yml);
  I remove the image or text promptly, and you may be asked for a different cover.

Details: [README.md#license](README.md#license); the DSX name: [TRADEMARKS.md](TRADEMARKS.md).
