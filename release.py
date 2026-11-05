"""
Publish a new version of ROK Gem Helper.

    python release.py 1.1.0

First add the version to CHANGELOG at the top of rok_march_alert.py (that text is
shown in the app's "What's new" and becomes the release notes). Then this:
1. sets APP_VERSION in rok_march_alert.py
2. builds the exe (dist/ROK Gem Helper.exe)
3. commits and pushes the code
4. creates the GitHub release v1.1.0 with ROK-Gem-Helper.exe + its .sha256 file

Everyone running an older copy then sees "Update available" on their next start.
Needs the GitHub CLI (gh), signed in once with:  gh auth login
"""
import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "rok_march_alert.py")
ASSET = "ROK-Gem-Helper.exe"


def gh():
    return shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def run(*cmd):
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=HERE, check=True)


def changelog_notes(src, ver):
    """Bullet list for this version from CHANGELOG in rok_march_alert.py."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CHANGELOG":
            for v, _date, items in ast.literal_eval(node.value):
                if v == ver:
                    return "\n".join(f"- {it}" for it in items)
    return None


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit(__doc__)
    ver = sys.argv[1]

    src = open(APP, encoding="utf-8").read()
    notes = changelog_notes(src, ver)
    if not notes:
        sys.exit(f"Add a CHANGELOG entry for {ver} in rok_march_alert.py first.")
    src, n = re.subn(r'^APP_VERSION = "[^"]*"', f'APP_VERSION = "{ver}"', src, flags=re.M)
    if n != 1:
        sys.exit("APP_VERSION line not found in rok_march_alert.py")
    with open(APP, "w", encoding="utf-8") as f:
        f.write(src)

    # build outside dist/, so a copy of the app that is open doesn't block the build
    work = tempfile.mkdtemp(prefix="rgh_build_")
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--workpath", work,
        "--distpath", os.path.join(work, "dist"), "ROKGemHelper.spec")
    built = os.path.join(work, "dist", "ROK Gem Helper.exe")

    out = tempfile.mkdtemp(prefix="rgh_release_")
    exe = os.path.join(out, ASSET)
    shutil.copyfile(built, exe)
    try:
        shutil.copyfile(built, os.path.join(HERE, "dist", "ROK Gem Helper.exe"))
    except OSError:
        print("dist/ROK Gem Helper.exe is open, so it was not replaced; "
              "copies from v1.0.0 on will offer the update themselves")
    shutil.rmtree(work, ignore_errors=True)
    digest = hashlib.sha256(open(exe, "rb").read()).hexdigest()
    with open(exe + ".sha256", "w") as f:
        f.write(f"{digest}  {ASSET}\n")

    run("git", "add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode:
        run("git", "commit", "-m", f"Release v{ver}\n\n{notes}")
    run("git", "push")
    run(gh(), "release", "create", f"v{ver}", exe, exe + ".sha256",
        "--title", f"ROK Gem Helper v{ver}", "--notes", notes)
    shutil.rmtree(out, ignore_errors=True)
    print(f"\nPublished v{ver}.")


if __name__ == "__main__":
    main()
