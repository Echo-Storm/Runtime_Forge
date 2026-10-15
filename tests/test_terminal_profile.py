"""
Tests for the Windows Terminal Profile component: merging the bundled profiles
into a user's settings.json (core/terminal_profile.py) rather than replacing it.

Never touches the real Windows Terminal settings - the target is a temp file.

Run directly:
    venv\\Scripts\\python.exe tests\\test_terminal_profile.py
"""

import copy
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import core.definitions as definitions
from core import terminal_profile as tp
from core.logger import setup_logging

tmp = Path(tempfile.mkdtemp(prefix="rf_terminal_"))
setup_logging(tmp)
results = {}

source = definitions._terminal_profile_source()
bundled = tp.parse_settings(source.read_text(encoding="utf-8"))
bundled_profiles = tp._profile_list(bundled)
results["bundled_source_exists_and_parses"] = source.is_file() and len(bundled_profiles) >= 15

# ---- the tolerant parser
commented = '''﻿{
    // a line comment
    "url": "https://aka.ms/terminal",   /* a block comment */
    "list": [1, 2, 3,],
    "text": "has // slashes, /* stars */ and a \\" quote",
    "nested": {"a": [ {"b": 1,}, ],},
}'''
parsed = tp.parse_settings(commented)
results["parser_drops_comments"] = parsed["url"] == "https://aka.ms/terminal"
results["parser_drops_trailing_commas"] = parsed["list"] == [1, 2, 3] and parsed["nested"] == {"a": [{"b": 1}]}
results["parser_keeps_comment_lookalikes_inside_strings"] = parsed["text"] == 'has // slashes, /* stars */ and a " quote'
for bad in ("not json", "[1, 2]", ""):
    try:
        tp.parse_settings(bad)
        results[f"parser_rejects_{bad or 'empty'}".replace(" ", "_")] = False
    except ValueError:
        results[f"parser_rejects_{bad or 'empty'}".replace(" ", "_")] = True

# ---- merge: a user with their own things
user = {
    "$schema": "https://example.test/own-schema",
    "defaultProfile": "{my-own-default}",
    "theme": "light",
    "actions": [{"command": "copy", "keys": "ctrl+c"}],
    "profiles": {
        "defaults": {"font": {"face": "Fira Code", "size": 13}, "opacity": 40},
        "list": [
            {"guid": "{my-own-default}", "name": "My Shell", "commandline": "mysh.exe"},
            copy.deepcopy(bundled_profiles[0]),                     # one of ours, hidden by the user
        ],
    },
    "schemes": [{"name": "My Scheme", "background": "#000000"}],
}
user["profiles"]["list"][1]["hidden"] = True
user["profiles"]["list"][1]["name"] = "old name of ours"             # stale copy of our profile
merged = tp.merge(user, bundled)
mlist = tp._profile_list(merged)
guids = [p["guid"].lower() for p in mlist]

results["users_own_profile_survives_in_place"] = mlist[0] == {"guid": "{my-own-default}", "name": "My Shell", "commandline": "mysh.exe"}
results["every_bundled_profile_is_present"] = all(p["guid"].lower() in guids for p in bundled_profiles)
results["no_profile_is_duplicated"] = len(guids) == len(set(guids))
results["stale_copy_of_ours_is_refreshed"] = next(p for p in mlist if p["guid"].lower() == bundled_profiles[0]["guid"].lower())["name"] == bundled_profiles[0]["name"]
results["users_show_hide_choice_is_kept"] = next(p for p in mlist if p["guid"].lower() == bundled_profiles[0]["guid"].lower()).get("hidden") is True
results["users_scheme_survives"] = any(s["name"] == "My Scheme" for s in merged["schemes"])
results["bundled_schemes_are_added"] = all(any(s["name"] == b["name"] for s in merged["schemes"]) for b in bundled["schemes"])
results["users_defaults_are_never_overwritten"] = merged["profiles"]["defaults"]["font"] == {"face": "Fira Code", "size": 13} and merged["profiles"]["defaults"]["opacity"] == 40
results["missing_defaults_are_filled_in"] = merged["profiles"]["defaults"]["historySize"] == bundled["profiles"]["defaults"]["historySize"]
results["users_default_profile_theme_actions_schema_untouched"] = (
    merged["defaultProfile"] == "{my-own-default}" and merged["theme"] == "light"
    and merged["actions"] == user["actions"] and merged["$schema"] == "https://example.test/own-schema"
)
results["merge_does_not_modify_its_input"] = user["profiles"]["list"][1]["name"] == "old name of ours" and len(user["schemes"]) == 1
results["merge_is_idempotent"] = tp.merge(merged, bundled) == merged
results["is_applied_after_merge"] = tp.is_applied(merged, bundled)
results["is_not_applied_before_merge"] = not tp.is_applied(user, bundled)
results["is_applied_ignores_unrelated_user_settings"] = tp.is_applied({**merged, "theme": "dark", "extra": 1}, bundled)
broken = copy.deepcopy(merged)
broken["profiles"]["list"][1]["commandline"] = "changed.exe"
results["is_not_applied_when_one_of_ours_differs"] = not tp.is_applied(broken, bundled)
broken = copy.deepcopy(merged)
broken["schemes"] = [s for s in broken["schemes"] if s["name"] != bundled["schemes"][0]["name"]]
results["is_not_applied_when_a_scheme_is_missing"] = not tp.is_applied(broken, bundled)
results["merging_into_an_empty_file_gives_the_bundled_profiles"] = tp.is_applied(tp.merge({}, bundled), bundled)
old_layout = tp.merge({"profiles": [{"guid": "{legacy}", "name": "Legacy"}]}, bundled)
results["pre_1_0_list_layout_is_upgraded"] = any(p["guid"] == "{legacy}" for p in tp._profile_list(old_layout)) and tp.is_applied(old_layout, bundled)

# ---- python profiles go through the launcher, so any install folder works
py_profiles = [p for p in bundled_profiles if "Python 3." in p["name"]]
results["python_profiles_use_the_py_launcher"] = len(py_profiles) == 5 and all(p["commandline"].startswith("py.exe -3.") for p in py_profiles)
results["python_314_has_a_profile"] = any(p["commandline"] == "py.exe -3.14" for p in py_profiles)

# ---- the component, against a temp target
target = tmp / "Packages" / "Microsoft.WindowsTerminal_8wekyb3d8bbwe" / "LocalState" / "settings.json"
real_target = definitions._TERMINAL_PROFILE_TARGET
definitions._TERMINAL_PROFILE_TARGET = target
ctx = definitions.InstallContext(temp_dir=tmp, dry_run=False)
try:
    results["not_installed_when_no_settings_file"] = not definitions._terminal_profile_is_installed().installed

    # Terminal not installed (no package folder): refuse, create nothing
    results["refuses_when_terminal_is_not_installed"] = definitions._terminal_profile_install(ctx) is False and not (tmp / "Packages").exists()

    target.parent.mkdir(parents=True)                       # Terminal "installed", no settings.json yet
    results["dry_run_writes_nothing"] = definitions._terminal_profile_install(definitions.InstallContext(temp_dir=tmp, dry_run=True)) and not target.exists()
    results["fresh_install_succeeds"] = definitions._terminal_profile_install(ctx) is True
    results["fresh_install_writes_the_bundled_profiles"] = tp.is_applied(tp.parse_settings(target.read_text(encoding="utf-8")), bundled)
    results["is_installed_true_after_install"] = definitions._terminal_profile_is_installed().installed
    results["no_backup_needed_for_a_fresh_install"] = not list(target.parent.glob("settings.json.bak_*"))

    # the user then customises it: still "installed"
    live = json.loads(target.read_text(encoding="utf-8"))
    live["profiles"]["list"].append({"guid": "{mine}", "name": "Mine"})
    live["theme"] = "dark"
    target.write_text(json.dumps(live), encoding="utf-8")
    results["customising_the_file_does_not_make_it_uninstalled"] = definitions._terminal_profile_is_installed().installed

    # someone edits one of our profiles -> not installed; reinstalling restores it and keeps the rest
    live["profiles"]["list"][0]["colorScheme"] = "Something Else"
    target.write_text(json.dumps(live), encoding="utf-8")
    results["an_edited_profile_of_ours_reads_as_not_installed"] = not definitions._terminal_profile_is_installed().installed
    results["reapply_succeeds"] = definitions._terminal_profile_install(ctx) is True
    after = json.loads(target.read_text(encoding="utf-8"))
    results["reapply_restores_ours"] = definitions._terminal_profile_is_installed().installed
    results["reapply_keeps_the_users_profile_and_theme"] = any(p.get("guid") == "{mine}" for p in tp._profile_list(after)) and after["theme"] == "dark"
    backups = list(target.parent.glob("settings.json.bak_*"))
    results["reapply_backs_up_first_with_the_old_content"] = len(backups) == 1 and "Something Else" in backups[0].read_text(encoding="utf-8")

    # a settings.json with comments is understood (and survives in the backup)
    commented_file = '// my notes\n' + json.dumps(after, indent=2).replace('"theme": "dark"', '"theme": "dark", // keep dark\n')
    target.write_text(commented_file, encoding="utf-8")
    results["settings_with_comments_still_parse_for_detection"] = definitions._terminal_profile_is_installed().installed

    # unreadable settings: don't touch it
    target.write_text("{ this is not json", encoding="utf-8")
    results["unreadable_settings_reads_as_not_installed"] = not definitions._terminal_profile_is_installed().installed
    results["unreadable_settings_are_left_untouched"] = (
        definitions._terminal_profile_install(ctx) is False and target.read_text(encoding="utf-8") == "{ this is not json"
    )
finally:
    definitions._TERMINAL_PROFILE_TARGET = real_target

for name, ok in results.items():
    print(f"{name}: {ok}")
all_ok = all(results.values())
print(f"ALL_OK: {all_ok}")
sys.exit(0 if all_ok else 1)
