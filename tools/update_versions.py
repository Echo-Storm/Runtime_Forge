r"""
Regenerates data/versions.json - the published catalog the app reads instead of
asking api.github.com about ~20 projects on every scan (see core/published.py).

It resolves each GitHub-hosted component LIVE (never from the catalog, never
from a pinned fallback - strict mode makes a failed lookup an error rather than
publishing an old pin as "latest") and records its version, download URL and the
SHA-256 GitHub publishes. An entry that can't be fully resolved is skipped (and
reported), so one flaky lookup never poisons the rest.

    venv\Scripts\python.exe tools\update_versions.py            # writes data/versions.json
    venv\Scripts\python.exe tools\update_versions.py --dry-run  # prints, writes nothing

Set GITHUB_TOKEN (or GH_TOKEN) first: 15 lookups don't fit in 60 requests/hour
alongside anything else. The scheduled workflow
(.github/workflows/update-versions.yml) runs this daily.
"""
import datetime
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import published
from core.logger import setup_logging

OUTPUT = ROOT / "data" / "versions.json"


def build_entries(components, repos=None, log=print):
    """-> (entries, problems). `components`: key -> Component (anything with resolve_latest())."""
    entries, problems = {}, []
    for key, repo in (repos or published.REPOS).items():
        component = components.get(key)
        if component is None or component.resolve_latest is None:
            problems.append(f"{key}: no such component")
            continue
        try:
            info = component.resolve_latest()
        except Exception as e:  # noqa: BLE001 - report and continue
            problems.append(f"{key} ({repo}): {e}")
            continue
        if info is None or not info.sha256 or not info.url.startswith("https://github.com/"):
            problems.append(f"{key} ({repo}): incomplete result (needs a github.com URL and a SHA-256)")
            continue
        entries[repo] = {"version": info.version, "url": info.url, "filename": info.filename, "sha256": info.sha256.lower()}
        log(f"  {key:10} {info.version:18} {info.filename}")
    return entries, problems


def main() -> int:
    dry = "--dry-run" in sys.argv
    published.disable()
    published.set_strict(True)
    setup_logging(Path(tempfile.mkdtemp(prefix="rf_versions_")))

    from core.definitions import build_components
    components = {c.key: c for c in build_components()}
    entries, problems = build_entries(components)

    document = {"schema": published.SCHEMA, "generated": datetime.date.today().isoformat(), "entries": dict(sorted(entries.items()))}
    text = json.dumps(document, indent=2) + "\n"
    print(f"\n{len(entries)} of {len(published.REPOS)} entries resolved")
    for problem in problems:
        print(f"  SKIPPED  {problem}")
    if dry:
        return 1 if problems else 0
    if not entries:
        print("Nothing resolved - leaving the existing file alone.")
        return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Keep the previous entry for anything that failed this time, so a transient error doesn't drop a component.
    if OUTPUT.is_file():
        try:
            previous = json.loads(OUTPUT.read_text(encoding="utf-8")).get("entries", {})
            for repo, old in previous.items():
                document["entries"].setdefault(repo, old)
            document["entries"] = dict(sorted(document["entries"].items()))
            text = json.dumps(document, indent=2) + "\n"
        except (OSError, ValueError):
            pass
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
