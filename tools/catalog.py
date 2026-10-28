#!/usr/bin/env python3
"""DSX-Mods catalog tool: validate | build | diff | check-links | intake | self-check.

Stdlib + Pillow (tools/requirements.txt). Run from anywhere; paths are relative to the repo root.

  python tools/catalog.py validate                 every mods/<id>/ against the rules; exit 1 on any error
  python tools/catalog.py build --out _site        _site/v1/catalog.json + _site/v1/covers/<sha256>.jpg
  python tools/catalog.py diff origin/main         what a change does, in words (link changes flagged)
  python tools/catalog.py check-links [id ...]     links answer (404/410/unreachable = dead, exit 1)
  python tools/catalog.py intake event.json        an accepted submit/update issue -> mods/<id>/ (prints the id)
  python tools/catalog.py self-check               asserts on synthetic mods; exit 0 when the rules hold

DSX enforces the same host allowlist, https rule and length caps on its side, so a rule changed here must also
change in DSX.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = 1
# serial = SERIAL_BASE + commits on main. Every DSX build ships a built-in catalog and ignores a published one with a
# lower serial; DSX builds carry built-in serials up to 28, so the base keeps every publish above them.
# Never lower it.
SERIAL_BASE = 100
COVER_SIZE = (1280, 720)
COVER_MAX_BYTES = 250 * 1024
COVER_INPUT_MAX_BYTES = 10 * 1024 * 1024
COVER_MIN_SIZE = (320, 180)
COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp", "cover.avif")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$")
MOD_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
GITHUB_USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")
FEATURES = ("triggers", "lights", "rumble", "haptics", "audio", "remap")
TRANSPORTS = ("udp", "pipe")
STATUSES = ("listed", "deprecated")
# Characters per field. DSX drops an entry over these caps.
CAPS = {"name": 80, "author": 60, "game": 100, "summary": 100, "description": 2000, "note": 160, "reason": 200, "url": 300}
MANIFEST_KEYS = {"$schema", "name", "author", "maintainers", "games", "summary", "description", "note", "links",
                 "features", "transports", "mod_ids", "requires", "status", "reason"}
CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")


def length(value: str) -> int:
    """Characters as DSX counts them (UTF-16 units), so an emoji counts two and CI and DSX agree on every cap."""
    return len(value.encode("utf-16-le")) // 2


def allowed_hosts() -> list[str]:
    lines = (ROOT / "tools" / "allowed-hosts.txt").read_text(encoding="utf-8").splitlines()
    return [line.strip().lower() for line in lines if line.strip() and not line.startswith("#")]


def host_allowed(host: str, hosts: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == entry or host.endswith("." + entry) for entry in hosts)


def check_url(value, where: str, hosts: list[str]) -> list[str]:
    if not isinstance(value, str) or not value:
        return [f"{where}: must be a link"]
    if len(value) > CAPS["url"] or not value.isascii() or any(c in value for c in '"<>\\^`{|}'):
        return [f"{where}: at most {CAPS['url']} characters, ASCII only, none of \" < > \\ ^ ` {{ | }} (percent-encode them)"]
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https":
        return [f"{where}: must start with https://"]
    if not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        return [f"{where}: must be a plain https address (no user, password or port)"]
    if any(c.isspace() for c in value):
        return [f"{where}: contains spaces"]
    if not host_allowed(parsed.hostname, hosts):
        return [f"{where}: {parsed.hostname} is not on the allowed sites list (tools/allowed-hosts.txt)"]
    return []


def check_text(value, where: str, cap: int, required: bool = True, multiline: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, str) or not value.strip():
        return [f"{where}: required text"]
    errors = []
    if length(value) > cap:
        errors.append(f"{where}: {length(value)} characters, at most {cap}")
    text = value.replace("\n", "") if multiline else value
    if CONTROL_RE.search(text) or (not multiline and "\n" in value):
        errors.append(f"{where}: contains control characters" + ("" if multiline else " or line breaks"))
    if value != value.strip():
        errors.append(f"{where}: starts or ends with spaces")
    return errors


def check_manifest(mod_id: str, data, hosts: list[str]) -> list[str]:
    """The rules for one mods/<id>/mod.json. An empty list means it passes."""
    if not ID_RE.match(mod_id):
        return [f"folder name '{mod_id}': 3-48 characters of a-z, 0-9 and '-', not starting or ending with '-'"]
    if not isinstance(data, dict):
        return ["mod.json must be a JSON object"]
    errors = [f"unknown field '{key}'" for key in data if key not in MANIFEST_KEYS]
    errors += check_text(data.get("name"), "name", CAPS["name"])
    author = data.get("author")
    if not isinstance(author, dict) or set(author) - {"name", "url"}:
        errors.append("author: must be {\"name\": ..., \"url\": ...(optional)}")
    else:
        errors += check_text(author.get("name"), "author.name", CAPS["author"])
        if isinstance(author.get("name"), str) and author["name"].startswith("@"):
            errors.append("author.name: without the leading @ (DSX adds it)")
        if "url" in author:
            errors += check_url(author["url"], "author.url", hosts)
    maintainers = data.get("maintainers", [])
    if not isinstance(maintainers, list) or len(maintainers) > 10 or not all(
            isinstance(m, str) and GITHUB_USER_RE.match(m) for m in maintainers):
        errors.append("maintainers: up to 10 GitHub user names")
    games = data.get("games")
    if not isinstance(games, list) or not 1 <= len(games) <= 10:
        errors.append("games: 1 to 10 games")
    else:
        for i, game in enumerate(games):
            where = f"games[{i}]"
            if not isinstance(game, dict) or set(game) - {"name", "steam_app_id", "aliases"}:
                errors.append(f"{where}: must be {{\"name\", \"steam_app_id\", \"aliases\"}}")
                continue
            errors += check_text(game.get("name"), f"{where}.name", CAPS["game"])
            app_id = game.get("steam_app_id")
            if app_id is not None and (type(app_id) is not int or not 0 < app_id < 2 ** 31):
                errors.append(f"{where}.steam_app_id: a positive whole number or null")
            aliases = game.get("aliases", [])
            if not isinstance(aliases, list) or len(aliases) > 10:
                errors.append(f"{where}.aliases: up to 10 names")
            else:
                for j, alias in enumerate(aliases):
                    errors += check_text(alias, f"{where}.aliases[{j}]", CAPS["game"])
    errors += check_text(data.get("summary"), "summary", CAPS["summary"])
    errors += check_text(data.get("description"), "description", CAPS["description"], multiline=True)
    errors += check_text(data.get("note"), "note", CAPS["note"], required=False)
    links = data.get("links")
    if not isinstance(links, dict) or "home" not in links or set(links) - {"home", "source"}:
        errors.append("links: {\"home\": ..., \"source\": ...(optional)}")
    else:
        for key, value in links.items():
            errors += check_url(value, f"links.{key}", hosts)
    for key, allowed in (("features", FEATURES), ("transports", TRANSPORTS)):
        values = data.get(key)
        if not isinstance(values, list) or not values or len(set(map(str, values))) != len(values) or any(
                v not in allowed for v in values):
            errors.append(f"{key}: one or more of {', '.join(allowed)}, each once")
    mod_ids = data.get("mod_ids", [])
    if not isinstance(mod_ids, list) or len(mod_ids) > 10 or not all(isinstance(m, str) and MOD_ID_RE.match(m) for m in mod_ids):
        errors.append("mod_ids: up to 10 ModId values of 1-64 characters A-Z a-z 0-9 . _ -")
    requires = data.get("requires", {})
    if not isinstance(requires, dict) or set(requires) - {"dsx"} or (
            "dsx" in requires and not (isinstance(requires["dsx"], str) and VERSION_RE.match(requires["dsx"]))):
        errors.append("requires: {\"dsx\": \"3.1\"} (a version number) or nothing")
    status = data.get("status")
    if status not in STATUSES:
        errors.append(f"status: one of {', '.join(STATUSES)}")
    if status == "deprecated":
        errors += check_text(data.get("reason"), "reason", CAPS["reason"])
    elif "reason" in data:
        errors.append("reason: only for status deprecated")
    return errors


def find_cover(folder: Path) -> Path | None:
    found = [folder / name for name in COVER_NAMES if (folder / name).is_file()]
    return found[0] if len(found) == 1 else None


def check_folder(folder: Path, hosts: list[str]) -> list[str]:
    errors = []
    names = {p.name for p in folder.iterdir()}
    covers = [n for n in names if n in COVER_NAMES]
    for extra in sorted(names - {"mod.json", *COVER_NAMES}):
        errors.append(f"{extra}: only mod.json and one cover.(jpg|png|webp|avif) belong in a mod folder")
    if len(covers) > 1:
        errors.append(f"more than one cover: {', '.join(sorted(covers))}")
    try:
        data = json.loads((folder / "mod.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return errors + ["mod.json is missing"]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return errors + [f"mod.json is not valid UTF-8 JSON: {error}"]
    if (folder / "mod.json").read_bytes().startswith(b"\xef\xbb\xbf"):
        errors.append("mod.json starts with a byte order mark; save it as UTF-8 without BOM")
    errors += check_manifest(folder.name, data, hosts)
    if len(covers) == 1:
        try:
            normalize_cover((folder / covers[0]).read_bytes())
        except ValueError as error:
            errors.append(f"{covers[0]}: {error}")
    return errors


def normalize_cover(raw: bytes) -> bytes:
    """Any accepted image -> 1280x720 JPEG (centre crop, EXIF stripped, <= 250 KB). ValueError when unusable."""
    from PIL import Image, ImageOps
    if len(raw) > COVER_INPUT_MAX_BYTES:
        raise ValueError(f"{len(raw)} bytes, at most {COVER_INPUT_MAX_BYTES}")
    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP", "AVIF"):
                raise ValueError(f"{image.format} images are not accepted (JPEG, PNG, WebP or AVIF)")
            if image.width < COVER_MIN_SIZE[0] or image.height < COVER_MIN_SIZE[1]:
                raise ValueError(f"{image.width}x{image.height}, at least {COVER_MIN_SIZE[0]}x{COVER_MIN_SIZE[1]}")
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                image = Image.new("RGB", rgba.size)
                image.paste(rgba, mask=rgba.getchannel("A"))
            else:
                image = image.convert("RGB")
            image = ImageOps.fit(image, COVER_SIZE, Image.Resampling.LANCZOS)
    except (OSError, Image.DecompressionBombError, SyntaxError) as error:
        raise ValueError(f"not a readable image ({error})") from None
    for quality in range(85, 49, -5):
        out = io.BytesIO()
        image.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= COVER_MAX_BYTES:
            return out.getvalue()
    raise ValueError("does not fit in 250 KB as a 1280x720 JPEG")


def mod_folders() -> list[Path]:
    mods = ROOT / "mods"
    return sorted(p for p in mods.iterdir() if p.is_dir()) if mods.is_dir() else []


def validate_all() -> dict[str, list[str]]:
    hosts = allowed_hosts()
    problems: dict[str, list[str]] = {}
    seen_mod_ids: dict[str, str] = {}
    for folder in mod_folders():
        errors = check_folder(folder, hosts)
        try:
            data = json.loads((folder / "mod.json").read_text(encoding="utf-8"))
            mod_ids = data.get("mod_ids", []) if isinstance(data, dict) else []
            for value in mod_ids if isinstance(mod_ids, list) else []:
                key = str(value).lower()
                if key in seen_mod_ids:
                    errors.append(f"mod_ids: '{value}' is already used by {seen_mod_ids[key]}")
                seen_mod_ids.setdefault(key, folder.name)
        except (OSError, ValueError):
            pass
        if errors:
            problems[folder.name] = errors
    return problems


def git(*args: str, binary: bool = False):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return result.stdout if binary else result.stdout.decode("utf-8")


def history() -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    """Per mod: the index of the commit that added it (list order), the date it was added and last changed."""
    order: dict[str, int] = {}
    added: dict[str, str] = {}
    updated: dict[str, str] = {}
    try:
        out = git("log", "--reverse", "--format=%x01%H %cs", "--name-only", "--", "mods")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return order, added, updated
    for index, block in enumerate(out.split("\x01")[1:]):
        lines = [line for line in block.splitlines() if line.strip()]
        date = lines[0].split()[1]
        for name in lines[1:]:
            parts = name.split("/")
            if len(parts) >= 3:
                order.setdefault(parts[1], index)
                added.setdefault(parts[1], date)
                updated[parts[1]] = date
    return order, added, updated


def build(out: Path, serial: int | None) -> dict:
    problems = validate_all()
    if problems:
        raise SystemExit("build refused, validate first:\n" + "\n".join(f"{k}: {e}" for k, v in problems.items() for e in v))
    try:
        commit = git("rev-parse", "HEAD").strip()
        generated = git("show", "-s", "--format=%cI", "HEAD").strip()
        serial = serial or SERIAL_BASE + int(git("rev-list", "--count", "HEAD").strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit, generated, serial = "", "1970-01-01T00:00:00Z", serial or 1
    order, added, updated = history()
    covers = out / "v1" / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    entries = []
    for folder in sorted(mod_folders(), key=lambda f: (order.get(f.name, 1 << 30), f.name)):
        data = json.loads((folder / "mod.json").read_text(encoding="utf-8"))
        entry = {"id": folder.name}
        entry.update({k: v for k, v in data.items() if k not in ("$schema", "maintainers")})
        entry.setdefault("mod_ids", [])
        for game in entry["games"]:
            game.setdefault("steam_app_id", None)
            game.setdefault("aliases", [])
        if cover := find_cover(folder):
            jpeg = normalize_cover(cover.read_bytes())
            sha = hashlib.sha256(jpeg).hexdigest()
            (covers / f"{sha}.jpg").write_bytes(jpeg)
            entry["cover"] = {"path": f"covers/{sha}.jpg", "sha256": sha, "width": COVER_SIZE[0], "height": COVER_SIZE[1]}
        day = generated[:10]
        entry["added"] = added.get(folder.name, day)
        entry["updated"] = updated.get(folder.name, day)
        entries.append(entry)
    catalog = {"schema": SCHEMA, "serial": serial, "generated": generated, "commit": commit, "mods": entries}
    data = json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > 1024 * 1024:
        raise SystemExit(f"catalog.json is {len(data)} bytes; DSX reads at most 1 MiB")
    (out / "v1" / "catalog.json").write_bytes(data)
    return catalog


def manifests_at(ref: str) -> dict[str, tuple[dict, str | None]]:
    """Manifest and cover hash of every mod at a git ref."""
    result = {}
    try:
        names = git("ls-tree", "-r", "--name-only", ref, "--", "mods").splitlines()
    except subprocess.CalledProcessError:
        return result
    for name in names:
        parts = name.split("/")
        if len(parts) == 3 and parts[2] == "mod.json":
            covers = [n for n in names if n.startswith(f"mods/{parts[1]}/") and n.split("/")[-1] in COVER_NAMES]
            cover = hashlib.sha256(git("show", f"{ref}:{covers[0]}", binary=True)).hexdigest() if covers else None
            try:
                result[parts[1]] = (json.loads(git("show", f"{ref}:{name}")), cover)
            except json.JSONDecodeError:
                result[parts[1]] = ({}, cover)
    return result


def manifests_now() -> dict[str, tuple[dict, str | None]]:
    result = {}
    for folder in mod_folders():
        cover = find_cover(folder)
        try:
            data = json.loads((folder / "mod.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        result[folder.name] = (data, hashlib.sha256(cover.read_bytes()).hexdigest() if cover else None)
    return result


def flatten(value, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key != "$schema":
                out.update(flatten(item, f"{prefix}.{key}" if prefix else key))
        return out
    if isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
        out = {}
        for i, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{i}]"))
        return out
    return {prefix: json.dumps(value, ensure_ascii=False)}


def describe_diff(before: dict, after: dict) -> list[str]:
    """Plain lines a reviewer reads: adds, removes, every changed field; link changes start with LINK CHANGE."""
    lines = []
    for mod_id in sorted(set(before) | set(after)):
        if mod_id not in before:
            data = after[mod_id][0]
            links = ", ".join(f"{k} {v}" for k, v in data.get("links", {}).items()) if isinstance(data.get("links"), dict) else "?"
            lines.append(f"adds {mod_id} ({data.get('name', '?')}; {links})")
            continue
        if mod_id not in after:
            lines.append(f"removes {mod_id} ({before[mod_id][0].get('name', '?')})")
            continue
        old, new = flatten(before[mod_id][0]), flatten(after[mod_id][0])
        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key):
                link = key.startswith("links.") or key == "author.url"
                lines.append(f"{'LINK CHANGE: ' if link else ''}changes {key} of {mod_id} from {old.get(key, '(none)')} to {new.get(key, '(none)')}")
        if before[mod_id][1] != after[mod_id][1]:
            lines.append(f"changes the cover of {mod_id}")
    return lines


def check_links(ids: list[str]) -> dict[str, list[tuple[str, str, str]]]:
    """Per mod: (field, url, verdict) where verdict is ok, dead (...) or unsure (...)."""
    report: dict[str, list[tuple[str, str, str]]] = {}
    for mod_id, (data, _) in manifests_now().items():
        if ids and mod_id not in ids:
            continue
        urls = [(f"links.{k}", v) for k, v in (data.get("links") or {}).items()]
        if isinstance(data.get("author"), dict) and data["author"].get("url"):
            urls.append(("author.url", data["author"]["url"]))
        report[mod_id] = [(field, url, probe(url)) for field, url in urls]
    return report


def probe(url: str) -> str:
    headers = {"User-Agent": "DSX-Mods link check (+https://github.com/Paliverse/DSX-Mods)"}
    status = None
    for method in ("HEAD", "GET"):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method=method, headers=headers), timeout=20) as response:
                return "ok" if response.status < 400 else f"unsure ({response.status})"
        except urllib.error.HTTPError as error:
            status = error.code
            if status in (404, 410) and method == "GET":
                return f"dead ({status})"
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if method == "GET":
                return f"dead ({getattr(error, 'reason', error)})"
    # Sites such as Nexus Mods answer 403 or 429 to robots; a person still reaches the page.
    return f"unsure ({status})"


FORM_FIELDS = {
    "Mod id": "id", "Mod name": "name", "Author name": "author", "Author page": "author_url", "Game": "game",
    "Steam App ID": "steam_app_id", "Summary": "summary", "Description": "description", "Requirement or limit": "note",
    "Mod page": "home", "Source code": "source", "What it controls": "features", "How it talks to DSX": "transports",
    "ModId values": "mod_ids", "Cover image": "cover",
}
FEATURE_LABELS = {"Adaptive triggers": "triggers", "Light bar and LEDs": "lights", "Rumble": "rumble",
                  "Haptics": "haptics", "Audio": "audio", "Button remapping": "remap"}
TRANSPORT_LABELS = {"UDP": "udp", "Mod pipe": "pipe"}
ATTACHMENT_RE = re.compile(r"https://github\.com/user-attachments/assets/[0-9a-fA-F-]{36}")


def parse_form(body: str) -> dict[str, str]:
    """GitHub renders an issue form as '### <label>' headings with the answer below; '_No response_' when empty."""
    answers: dict[str, str] = {}
    for section in re.split(r"^### ", body.replace("\r\n", "\n"), flags=re.M)[1:]:
        label, _, value = section.partition("\n")
        key = FORM_FIELDS.get(label.strip())
        value = value.strip()
        if key and value and value != "_No response_":
            answers[key] = value
    return answers


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")
    return value if len(value) >= 3 else (value + "-mod")[:48]


def checked(value: str, labels: dict[str, str]) -> list[str]:
    ticked = re.findall(r"^- \[[xX]\] (.+)$", value, flags=re.M)
    return [labels[label.strip()] for label in ticked if label.strip() in labels]


def intake(event_path: Path, fetch=None) -> str:
    """An accepted submit/update issue becomes mods/<id>/. Issue text is data only: it never reaches a shell."""
    event = json.loads(event_path.read_text(encoding="utf-8"))
    issue = event["issue"]
    labels = {label["name"] for label in issue.get("labels", [])}
    form = parse_form(issue.get("body") or "")
    if "update" in labels:
        mod_id = form.get("id", "").strip().lower()
        manifest_path = ROOT / "mods" / mod_id / "mod.json"
        if not ID_RE.match(mod_id) or not manifest_path.is_file():
            raise SystemExit(f"update: no mod with id '{mod_id}'")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif "submission" in labels:
        mod_id = slug(form.get("id") or form.get("name", ""))
        if (ROOT / "mods" / mod_id).exists():
            raise SystemExit(f"submit: mods/{mod_id} already exists; use the update form")
        data = {"$schema": "../../schema/mod.v1.schema.json", "status": "listed",
                "maintainers": [issue["user"]["login"]]}
    else:
        raise SystemExit("intake: the issue is neither a submission nor an update")
    if "name" in form:
        data["name"] = form["name"]
    if "author" in form:
        data.setdefault("author", {})["name"] = form["author"].lstrip("@")
    if "author_url" in form:
        data.setdefault("author", {})["url"] = form["author_url"]
    if "game" in form:
        games = [g.strip() for g in form["game"].splitlines() if g.strip()]
        data["games"] = [{"name": g} for g in games]
    if "steam_app_id" in form and data.get("games"):
        data["games"][0]["steam_app_id"] = int(form["steam_app_id"]) if form["steam_app_id"].isdigit() else form["steam_app_id"]
    for key in ("summary", "description", "note"):
        if key in form:
            data[key] = form[key]
    for key in ("home", "source"):
        if key in form:
            data.setdefault("links", {})[key] = form[key]
    # Unticked boxes still reach the issue body ("- [ ] ..."): only a ticked box changes the list.
    if features := checked(form.get("features", ""), FEATURE_LABELS):
        data["features"] = features
    if transports := checked(form.get("transports", ""), TRANSPORT_LABELS):
        data["transports"] = transports
    if "mod_ids" in form:
        data["mod_ids"] = [m for m in re.split(r"[\s,]+", form["mod_ids"]) if m]
    folder = ROOT / "mods" / mod_id
    folder.mkdir(parents=True, exist_ok=True)
    if match := ATTACHMENT_RE.search(form.get("cover", "")):
        raw = (fetch or download)(match.group(0))
        jpeg = normalize_cover(raw)
        for old in COVER_NAMES:
            (folder / old).unlink(missing_ok=True)
        (folder / "cover.jpg").write_bytes(jpeg)
    (folder / "mod.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mod_id


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DSX-Mods intake"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(COVER_INPUT_MAX_BYTES + 1)
    if len(data) > COVER_INPUT_MAX_BYTES:
        raise SystemExit("cover: larger than 10 MB")
    return data


def self_check() -> None:
    """Asserts on synthetic mods in a temporary copy of the rules. Fails loudly when a rule stops holding."""
    global ROOT
    from PIL import Image
    real_root = ROOT
    with tempfile.TemporaryDirectory() as temp:
        ROOT = Path(temp)
        try:
            (ROOT / "tools").mkdir()
            (ROOT / "tools" / "allowed-hosts.txt").write_text((real_root / "tools" / "allowed-hosts.txt").read_text(encoding="utf-8"), encoding="utf-8")
            hosts = allowed_hosts()
            good = {"name": "Test Mod", "author": {"name": "someone"}, "games": [{"name": "Game", "steam_app_id": 1}],
                    "summary": "One line.", "description": "Line one.\nLine two.", "links": {"home": "https://www.nexusmods.com/game/mods/1"},
                    "features": ["triggers"], "transports": ["udp"], "status": "listed"}
            assert check_manifest("test-mod", good, hosts) == [], check_manifest("test-mod", good, hosts)

            def broken(**changes):
                data = json.loads(json.dumps(good))
                data.update(changes)
                return check_manifest("test-mod", data, hosts)

            assert broken(links={"home": "https://evil.example.com/x"}), "a host off the allowlist must fail"
            assert broken(links={"home": "https://nexusmods.com.evil.io/x"}), "a look-alike host must fail"
            assert broken(links={"home": "http://www.nexusmods.com/x"}), "http must fail"
            assert broken(links={"home": "https://user@github.com/x"}), "user info must fail"
            assert broken(summary="x" * 101), "summary over 100 characters must fail"
            assert broken(summary="tab\there"), "control characters must fail"
            assert broken(name="two\nlines"), "a line break in a one-line field must fail"
            assert broken(description="bidi \u202e text"), "bidi overrides must fail"
            assert broken(status="deprecated"), "deprecated without a reason must fail"
            assert not broken(status="deprecated", reason="Replaced by another mod."), "deprecated with a reason passes"
            assert broken(features=["triggers", "triggers"]), "a repeated feature must fail"
            assert broken(transports=["tcp"]), "an unknown transport must fail"
            assert broken(download="https://github.com/x.exe"), "unknown fields (downloads) must fail"
            assert broken(author={"name": "@someone"}), "author names come without @"
            assert broken(games=[{"name": "Game", "steam_app_id": "1"}]), "steam_app_id must be a number"
            assert check_manifest("Bad_Id", good, hosts), "folder ids are lowercase slugs"
            assert host_allowed("race.elementfuture.com", hosts) and not host_allowed("elementfuture.com", hosts)

            def image(fmt: str, size=(460, 215), mode="RGB") -> bytes:
                out = io.BytesIO()
                Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(out, fmt)
                return out.getvalue()

            for fmt, mode in (("JPEG", "RGB"), ("PNG", "RGBA"), ("WEBP", "RGB"), ("AVIF", "RGB")):
                jpeg = normalize_cover(image(fmt, mode=mode))
                with Image.open(io.BytesIO(jpeg)) as out:
                    assert out.format == "JPEG" and out.size == COVER_SIZE, (fmt, out.format, out.size)
                    assert "exif" not in out.info, fmt
            for bad in (b"not an image", image("JPEG", size=(100, 100)), image("GIF")):
                try:
                    normalize_cover(bad)
                    raise AssertionError("an unusable cover must be refused")
                except ValueError:
                    pass

            mods = ROOT / "mods"
            for mod_id, mod_ids in (("first-mod", ["shared"]), ("second-mod", ["Shared"])):
                (mods / mod_id).mkdir(parents=True)
                data = dict(good, name=mod_id, mod_ids=mod_ids)
                (mods / mod_id / "mod.json").write_text(json.dumps(data), encoding="utf-8")
            (mods / "first-mod" / "cover.webp").write_bytes(image("WEBP"))
            problems = validate_all()
            assert list(problems) == ["second-mod"] and "already used" in problems["second-mod"][0], problems
            (mods / "second-mod" / "mod.json").write_text(json.dumps(dict(good, name="second-mod")), encoding="utf-8")
            (mods / "second-mod" / "notes.txt").write_text("x")
            assert "second-mod" in validate_all(), "stray files in a mod folder must fail"
            (mods / "second-mod" / "notes.txt").unlink()
            assert validate_all() == {}

            catalog = build(ROOT / "_site", serial=7)
            assert catalog["schema"] == 1 and catalog["serial"] == 7 and [m["id"] for m in catalog["mods"]] == ["first-mod", "second-mod"]
            first = catalog["mods"][0]
            cover_bytes = (ROOT / "_site" / "v1" / first["cover"]["path"]).read_bytes()
            assert hashlib.sha256(cover_bytes).hexdigest() == first["cover"]["sha256"] and len(cover_bytes) <= COVER_MAX_BYTES
            assert "maintainers" not in first and "$schema" not in first and "cover" not in catalog["mods"][1]
            assert json.loads((ROOT / "_site" / "v1" / "catalog.json").read_text(encoding="utf-8")) == catalog

            before = {"a": (good, None), "b": (good, "x")}
            after = {"a": (dict(good, links={"home": "https://github.com/x"}), None), "c": (good, None)}
            lines = describe_diff(before, after)
            assert any(line.startswith("LINK CHANGE: changes links.home of a") for line in lines), lines
            assert "removes b (Test Mod)" in lines and any(line.startswith("adds c") for line in lines), lines

            body = ("### Mod name\n\nNew Mod\n\n### Author name\n\n@Someone\n\n### Game\n\nSome Game\n\n### Steam App ID\n\n123\n\n"
                    "### Summary\n\nDoes things.\n\n### Description\n\nLong text.\n\n### Requirement or limit\n\n_No response_\n\n"
                    "### Mod page\n\nhttps://github.com/someone/new-mod\n\n### What it controls\n\n- [X] Adaptive triggers\n- [ ] Rumble\n- [x] Light bar and LEDs\n\n"
                    "### How it talks to DSX\n\n- [X] UDP\n\n### Cover image\n\n![cover](https://github.com/user-attachments/assets/0123abcd-0123-4567-89ab-0123456789ab)\n")
            event = ROOT / "event.json"
            event.write_text(json.dumps({"issue": {"body": body, "labels": [{"name": "submission"}, {"name": "accepted"}],
                                                   "user": {"login": "someone"}}}), encoding="utf-8")
            new_id = intake(event, fetch=lambda url: image("PNG"))
            made = json.loads((mods / new_id / "mod.json").read_text(encoding="utf-8"))
            assert new_id == "new-mod" and made["author"] == {"name": "Someone"} and made["features"] == ["triggers", "lights"], made
            assert made["games"] == [{"name": "Some Game", "steam_app_id": 123}] and "note" not in made and made["maintainers"] == ["someone"]
            assert validate_all() == {}, validate_all()

            update = ("### Mod id\n\nnew-mod\n\n### Summary\n\nDoes other things.\n\n### What it controls\n\n- [ ] Adaptive triggers\n- [ ] Rumble\n\n"
                      "### How it talks to DSX\n\n- [ ] UDP\n- [ ] Mod pipe\n")
            event.write_text(json.dumps({"issue": {"body": update, "labels": [{"name": "update"}, {"name": "accepted"}],
                                                   "user": {"login": "someone"}}}), encoding="utf-8")
            assert intake(event) == "new-mod"
            made = json.loads((mods / "new-mod" / "mod.json").read_text(encoding="utf-8"))
            assert made["summary"] == "Does other things." and made["features"] == ["triggers", "lights"] and made["transports"] == ["udp"], made
            assert validate_all() == {}, validate_all()
            assert broken(summary="\U0001F3AE" * 51), "caps count UTF-16 units, as DSX does"
            assert broken(links={"home": "https://github.com/ünicode"}), "links must be ASCII, as DSX requires"
            for bad in '"<>\\^`{|}':
                assert broken(links={"home": f"https://github.com/a{bad}b"}), f"{bad!r} makes DSX drop the link, so CI must refuse it"
            assert broken(name="line\u2028separator"), "U+2028 must fail"
        finally:
            ROOT = real_root
    print("self-check ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("build")
    p.add_argument("--out", type=Path, default=ROOT / "_site")
    p.add_argument("--serial", type=int)
    p = sub.add_parser("diff")
    p.add_argument("base")
    p = sub.add_parser("check-links")
    p.add_argument("ids", nargs="*")
    p = sub.add_parser("intake")
    p.add_argument("event", type=Path)
    sub.add_parser("self-check")
    args = parser.parse_args()
    summary = os.environ.get("GITHUB_STEP_SUMMARY")

    if args.command == "validate":
        problems = validate_all()
        for mod_id, errors in problems.items():
            for error in errors:
                print(f"::error file=mods/{mod_id}/mod.json::{mod_id}: {error}" if os.environ.get("GITHUB_ACTIONS") else f"{mod_id}: {error}")
        print(f"{len(mod_folders())} mods, {len(problems)} with problems")
        return 1 if problems else 0
    if args.command == "build":
        catalog = build(args.out, args.serial)
        print(f"built {len(catalog['mods'])} mods, serial {catalog['serial']} -> {args.out / 'v1'}")
        return 0
    if args.command == "diff":
        lines = describe_diff(manifests_at(args.base), manifests_now()) or ["no mod changes"]
        text = "\n".join(lines)
        print(text)
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                flagged = any(line.startswith("LINK CHANGE") for line in lines)
                handle.write("## Catalog changes\n\n" + ("**Link change: check the new address belongs to the mod's author.**\n\n" if flagged else "")
                             + "\n".join(f"- {line}" for line in lines) + "\n")
        return 0
    if args.command == "check-links":
        report = check_links(args.ids)
        dead = [(mod_id, field, url, verdict) for mod_id, rows in report.items() for field, url, verdict in rows if verdict.startswith("dead")]
        for mod_id, rows in report.items():
            for field, url, verdict in rows:
                print(f"{mod_id} {field} {url} {verdict}")
        if summary and dead:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("## Dead links\n\n" + "\n".join(f"- {m} {f} {u} {v}" for m, f, u, v in dead) + "\n")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as handle:
                handle.write("dead=" + json.dumps([{"id": m, "field": f, "url": u, "verdict": v} for m, f, u, v in dead]) + "\n")
        return 1 if dead else 0
    if args.command == "intake":
        mod_id = intake(args.event)
        print(mod_id)
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as handle:
                handle.write(f"id={mod_id}\n")
        return 0
    if args.command == "self-check":
        self_check()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
