"""
ROK Gem Helper - gem march timers for Rise of Kingdoms
------------------------------------------------------
Reads the Troops list on your screen and keeps one timer per march.

Setup inside the app:
  1. Settings > Marches: pick how many marches you have (1 ... 7).
  2. Open the Troops list and press F8 (or click Scan).
     Commanders are READ FROM THE SCREEN and filled into the march slots;
     after the first scan the count is locked (Reset unlocks it).
  3. Known gatherers are tracked. Any other commander shows "Not a Gatherer".

Per scan:
   "Marching to Gather 00:xx:xx" -> countdown + target (e.g. Level 3 Gem Mine)
                                    at zero the row flips to "Scan now" (silent):
                                    scan again to start the gathering timer
   "Gathering 00:xx:xx"          -> gather countdown + "Gathering Level 3 Gem Mine"
                                    (the mine it was last seen marching to)
If only some rows are visible: scan, scroll, scan again.
If a new commander shows up and every slot is taken (e.g. a fighting march was
swapped for a gatherer), it takes over an idle slot that wasn't in the scan.

Scan area: Set -> drag a box around the Troops list; scans then read only that
part of the screen (faster, fewer misreads). Full undoes it.

Restart: timers are saved in march_state.json and picked up again on start.
Ones that ran out while the app was closed end normally (gems counted, no alert).
Settings (lead, sound, Smart Gather, scan area, overlay on/off, collapsed sections)
are saved in march_settings.json.

Window: sidebar (march list, gem totals, hotkeys), header buttons (clear, move
overlay, overlay on/off, tray, Scan), cards for Marches / Gather Times / Settings
(the arrow folds a card), and the Log at the bottom. Hover the (i) icons for help.
Icons use Windows' built-in Segoe Fluent Icons font; logo files are in assets/.

Tray: the tray button hides the window and keeps everything running (the overlay stays
visible if it is on). Tray icon menu: Show / Overlay / Exit. The window's X
button closes the app.

Alerts: two Windows notifications per march: one at LEAD seconds before the
gather timer ends and one at half of that (e.g. 30s -> 30s and 15s). "(est.)"
means the timer came from a saved gather time. Sound On adds a short beep
(Windows hides notifications while a full-screen game runs; the beep still plays).

Gems: when a gather finishes, Gem Mine level x counts x*10 gems (L1=10 ... L4=40),
once per gather. A march seen marching on before its timer ended is counted
too, unless a scanned timer still had over a minute left (recalled). Total (kept
forever) and Today (resets at local midnight) show in the sidebar and are saved in
march_gems.json (+ march_gems.log).

Gather Times: for every detected commander type how long each Gem Mine level
(L1-L4) takes to clear, as MM:SS, then press the lock button.
Locked times are saved to march_times.json and re-loaded (and locked) the
next time that commander is detected. When a march ARRIVES at a Gem Mine, the
saved time for that level starts automatically and the row switches to
GATHERING, so no extra scan is needed. A later scan always overwrites it with
the real in-game timer. Unlock a commander to edit and re-lock to save.

Smart Gather (On by default): when a scan shows a march gathering and the
tracker knows when it arrived (a scan saw it marching), time since arrival +
time left = how long that commander takes for that Gem Mine level. The last 5
are kept per commander and level in march_smart.json; their median fills EMPTY
boxes in teal and updates as more come in. A time you typed is never replaced;
locking a row turns its teal times into your own.

Updates: on start the exe asks GitHub (UPDATE_REPO) for the latest release. If it
is newer than APP_VERSION a banner offers "Update now": the new exe is downloaded,
checked against its .sha256 file, swapped in (the old one is renamed to .old and
deleted on the next start) and the app restarts. Data files are not touched.
Publishing: raise APP_VERSION, build, then make a GitHub release tagged vX.Y.Z with
ROK-Gem-Helper.exe and ROK-Gem-Helper.exe.sha256 attached:
         add the version to CHANGELOG, then  python source/release.py X.Y.Z

Hotkeys:  F8 = scan    F9 = unlock/lock overlay for dragging    F10 = clear timers
          (change them in Settings > Hotkeys; saved in march_settings.json)

Setup (Windows):
  1. Install Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
  2. pip install mss pytesseract pillow opencv-python keyboard plyer pystray

Files:   the app keeps everything it saves (gems, times, settings, logs) in a
         "data" folder next to the exe; files from older versions are moved in.

Run:     python rok_gem_helper.py
Options: --marches 5 --lead 30 --region L T W H
         --test-image shot.png   (OCR test, no window)
"""
import argparse
import difflib
import json
import os
import queue
import re
import statistics
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

import cv2
import numpy as np
import pytesseract

APP_VERSION = "1.0.3"
UPDATE_REPO = "Tim1501/rok-gem-helper"     # GitHub repository new versions are published in
UPDATE_ASSET = "ROK-Gem-Helper.exe"       # release file name (+ ".sha256" checksum file)
HOTKEY_ACTIONS = (("scan", "Scan"), ("move", "Move"), ("clear", "Clear"))
DEFAULT_KEYS = {"scan": "f8", "move": "f9", "clear": "f10"}
MODIFIERS = {"ctrl", "shift", "alt", "windows", "left ctrl", "right ctrl", "left shift",
             "right shift", "left alt", "right alt", "alt gr", "left windows", "right windows"}
DONATE_URL = "https://paypal.me/DeepTak646"
DISCORD_NAME = "ChanaMasala"

# Newest first. Shown in the sidebar under "What's new"; release.py uses the
# entry of the version it publishes as the GitHub release notes.
CHANGELOG = [
    ("1.0.3", "2026-11-05", [
        "Change the Scan, Move and Clear hotkeys in Settings > Hotkeys",
        "What's new only shows lines that fit completely",
    ]),
    ("1.0.2", "2026-11-05", [
        "Donate button in the sidebar - any support is appreciated",
        "Found a bug? Contact @ChanaMasala on Discord (click the name to copy it)",
    ]),
    ("1.0.1", "2026-11-05", [
        "Tidier folder: your saved files now live in a 'data' folder",
        "Only works with the game set to English for now",
    ]),
    ("1.0.0", "2026-11-05", [
        "First public release",
        "F8 reads the Troops list and keeps a timer for every march",
        "Alerts before each gather ends, with optional beep",
        "Smart Gather learns gather times from your scans",
        "Gem counter, overlay, tray and scan area",
        "Updates itself when a new version is out",
    ]),
]

# full name -> short name (shown on the mini overlay)
GATHERERS = {
    "Seondeok": "Seondeok",
    "Ishida Mitsunari": "Ishida",
    "Cleopatra VII": "Cleopatra",
    "Pepin III": "Pepin",
    "Joan of Arc": "Joan",
    "Casimir III": "Casimir",
    "Matilda of Flanders": "Matilda",
    "Queen Tamar of Georgia": "Tamar",
    "Wak Chanil Ajaw": "Chanil",
    "Yahya ibn Khalid": "Khalid",
}
MAX_MARCHES = 7
TIME_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*:\s*(\d{2})")
COORD_RE = re.compile(r"[Xx]\s*[:;]\s*(\d{1,4})\s*[YyVv¥]\s*[:;]?\s*(\d{1,4})")
TARGET_RE = re.compile(r"l[vy][l1iI|]\.?\s*(\d)\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)", re.I)
NAME_RE = re.compile(r"[A-Za-z]{3,}.*[/|\\].*[A-Za-z]{3,}")
STATE_FILE = "march_state.json"
SLOTS_FILE = "march_slots.json"
TIMES_FILE = "march_times.json"
TIMES_LOG = "march_times.log"
LEVELS = (1, 2, 3, 4)
GEMS_FILE = "march_gems.json"
GEMS_LOG = "march_gems.log"
GEM_VALUE = {1: 10, 2: 20, 3: 30, 4: 40}
GEM_RED = "#e0605a"
GEMS = {"total": 0, "day": "", "daily": 0}
SETTINGS_FILE = "march_settings.json"


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_gems():
    try:
        with open(GEMS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        GEMS["total"] = int(d.get("total", 0))
        GEMS["day"] = str(d.get("day", ""))
        GEMS["daily"] = int(d.get("daily", 0))
    except Exception:
        pass
    roll_day()


def save_gems(note=None):
    try:
        with open(GEMS_FILE, "w", encoding="utf-8") as f:
            json.dump(GEMS, f, indent=2)
        if note:
            with open(GEMS_LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {note}  "
                        f"(today {GEMS['daily']}, total {GEMS['total']})\n")
    except Exception:
        pass


def roll_day():
    """Daily counter resets at local midnight."""
    today = time.strftime("%Y-%m-%d")
    if GEMS["day"] != today:
        GEMS["day"], GEMS["daily"] = today, 0
        save_gems()


def add_gems(n, note):
    roll_day()
    GEMS["total"] += n
    GEMS["daily"] += n
    save_gems(f"+{n} {note}")
GATHER_TIMES = {}   # commander -> {"locked": bool, "times": {level: seconds}}


def parse_mmss(text):
    """'25:30' -> 1530 seconds; None if empty/invalid."""
    m = re.fullmatch(r"\s*(\d{1,3})\s*:\s*([0-5]\d)\s*", text or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def fmt_mmss(secs):
    return f"{int(secs) // 60:02d}:{int(secs) % 60:02d}"


def load_times():
    try:
        with open(TIMES_FILE, encoding="utf-8") as f:
            data = json.load(f).get("commanders", {})
        for name, d in data.items():
            times = {}
            for k, v in d.get("times", {}).items():
                secs = parse_mmss(v)
                if secs and k[:1] == "L" and k[1:].isdigit():
                    times[int(k[1:])] = secs
            GATHER_TIMES[name] = {"locked": bool(d.get("locked")), "times": times}
    except Exception:
        pass


def save_times(note=None):
    try:
        out = {n: {"locked": d["locked"],
                   "times": {f"L{k}": fmt_mmss(v) for k, v in sorted(d["times"].items())}}
               for n, d in GATHER_TIMES.items()}
        with open(TIMES_FILE, "w", encoding="utf-8") as f:
            json.dump({"updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "commanders": out}, f, indent=2)
        if note:
            with open(TIMES_LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {note}\n")
    except Exception:
        pass


SMART_FILE = "march_smart.json"
SMART_KEEP = 5      # measurements kept per commander and level
SMART = {}          # commander -> {level: [measured seconds, newest last]}


def load_smart():
    try:
        with open(SMART_FILE, encoding="utf-8") as f:
            data = json.load(f).get("commanders", {})
        for name, lv in data.items():
            SMART[name] = {int(k[1:]): [int(v) for v in vals][-SMART_KEEP:]
                           for k, vals in lv.items() if k[:1] == "L" and k[1:].isdigit()}
    except Exception:
        pass


def save_smart():
    try:
        with open(SMART_FILE, "w", encoding="utf-8") as f:
            json.dump({"updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "commanders": {n: {f"L{k}": v for k, v in sorted(lv.items())}
                                      for n, lv in SMART.items()}}, f, indent=2)
    except Exception:
        pass


def learn_time(key, level, secs):
    """Store one measured gather time; returns how many are kept for that level."""
    vals = SMART.setdefault(key, {}).setdefault(level, [])
    vals.append(round(secs))
    del vals[:-SMART_KEEP]
    save_smart()
    return len(vals)


def smart_secs(key, level):
    """Learned gather time: the median, so one half-empty mine doesn't skew it."""
    vals = SMART.get(key, {}).get(level)
    return round(statistics.median(vals)) if vals else None


def gem_level(label):
    """'Level 3 Gem Mine' -> 3 (only Gem Mines L1-L4 have saved times)."""
    m = re.search(r"Level\s+(\d)\s+Gem", label or "")
    return int(m.group(1)) if m and int(m.group(1)) in LEVELS else None

# ---------------------------------------------------------------- theme
BG, SIDEBAR, CARD, GROUP = "#111317", "#17191d", "#1a1c21", "#212329"
FIELD, FIELD_HI, BORDER = "#2b2e35", "#363a42", "#272a30"
PANEL, INPUT_BG, LINE = CARD, FIELD, BORDER          # older names, still used by the overlay
TEXT, MUTED, WHITE = "#a1a6ae", "#6c717a", "#f3f4f6"
GRAY = MUTED
ACCENT, ACCENT_HI = "#2f8bff", "#539fff"
TEAL, RED, GREEN = "#3cc4b0", "#e5484d", "#3fcf74"
ORANGE, GOLD = "#f0a03c", "#e9c24f"
FLASH, FLASH_UPD = "#3d1f25", "#38311b"
SEL_OFF = "#4b4f57"
PINK = "#ff5c8a"

# Segoe Fluent Icons / Segoe MDL2 Assets glyphs (built into Windows 10/11)
IC = {"scan": "", "settings": "", "info": "", "sound": "",
      "timer": "", "clock": "", "trash": "", "move": "",
      "tray": "", "overlay": "", "area": "", "full": "",
      "lock": "", "unlock": "", "down": "", "up": "",
      "walk": "", "reset": "", "smart": "", "log": "",
      "warn": "", "sync": "", "people": "", "minus": "",
      "unknown": "", "heart": "", "keyboard": ""}


# ================================================================ core
lock = threading.RLock()


class Slot:
    def __init__(self):
        self.clear_identity()

    def clear_identity(self):
        self.key = None          # canonical commander name, or "ng:<name>" if not a gatherer
        self.full = ""           # full display name
        self.short = ""          # short overlay name
        self.raw = ""            # name as read (for non-gatherers)
        self.norm = ""
        self.gatherer = False
        self.target = None       # current marching target label
        self.coords = None
        self.last_target = None  # last mine it was marching to
        self.done = None         # ((coords, mine), when) of the last gather counted
        self.seen = 0            # last time a scan showed this commander
        self.reset()

    def reset(self):
        self.status = "idle"     # idle | walking | update | gathering | ready
        self.start = None
        self.walk_due = None
        self.gather_due = None
        self.level = None        # gem mine level being marched to
        self.est = False         # gather timer came from the saved time, not a scan
        self.alert2 = False      # second (half-lead) notification sent
        self.counted = False     # gems for this gather already counted
        self.arrived = None      # when it reached the mine (from a scanned march timer)


slots = [Slot() for _ in range(MAX_MARCHES)]
mine_by_coord = {}


def normalize(text):
    return re.sub(r"[^a-z]", "", text.lower())


# ---------------------------------------------------------------- OCR
def grab(region=None):
    import mss
    with mss.mss() as sct:
        if region:
            box = {"left": region[0], "top": region[1],
                   "width": region[2], "height": region[3]}
        else:
            box = sct.monitors[1]
        return np.array(sct.grab(box))[:, :, :3]


def ocr_lines(variant):
    d = pytesseract.image_to_data(variant, config="--psm 6",
                                  output_type=pytesseract.Output.DICT)
    lines = {}
    for i, w in enumerate(d["text"]):
        w = w.strip()
        if not w or float(d["conf"][i]) < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        e = lines.setdefault(key, {"w": [], "y": []})
        e["w"].append(w)
        e["y"].append(d["top"][i] + d["height"][i] / 2)
    out = [(sum(e["y"]) / len(e["y"]), " ".join(e["w"])) for e in lines.values()]
    return sorted(out)


def match_listed(text):
    """Return [(pos, ratio, full_name)] for gatherer names found in the text."""
    low = text.lower()
    letters = sum(ch.isalpha() for ch in low)
    if letters < 8 or TIME_RE.search(low) or "unit" in low or "gather" in low:
        return []
    found = []
    for full in GATHERERS:
        fl, n = full.lower(), len(full)
        best_r, best_i = 0.0, 0
        for i in range(max(1, len(low) - n + 1)):
            sm = difflib.SequenceMatcher(None, fl, low[i:i + n])
            if sm.quick_ratio() < 0.7:
                continue
            r = sm.ratio()
            if r > best_r:
                best_r, best_i = r, i
        if best_r >= 0.78:
            found.append((best_i, best_r, full))
    return found


def cluster_listed(c):
    best = None
    for _, t in c["texts"]:
        f = match_listed(t)
        if not f:
            continue
        top = max(r for _, r, _ in f)
        cand = min((p, n) for p, r, n in f if r >= top - 0.15)
        if best is None or top > best[0]:
            best = (top, cand[1])
    return best[1] if best else None


def cluster_units(c):
    for _, t in c["texts"]:
        low = t.lower()
        if "unit" in low and re.search(r"\d[\d,\.]{2,}", low):
            return True
    return False


def cluster_name_text(c):
    """Raw commander name for a 'A / B' line (primary commander)."""
    best = None
    for _, t in c["texts"]:
        if NAME_RE.search(t):
            if best is None or ("/" in t and "/" not in best):
                best = t
    if not best:
        return None
    head = re.split(r"[/|\\]", best)[0]
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", head)
    return " ".join(words[-3:]) if words else None


def cluster_timer(c):
    best = None
    for pi, t in c["texts"]:
        m = TIME_RE.search(t)
        if not m:
            continue
        h, mi, sec = map(int, m.groups())
        if mi >= 60 or sec >= 60:
            continue
        total, low = h * 3600 + mi * 60 + sec, t.lower()
        if re.search(r"marc|\bto\s+gat", low):
            kind, exact = "walking", "marching" in low
            if total > 3 * 3600:
                continue
        elif "gather" in low:
            kind, exact = "gathering", "gathering" in low
            if total > 30 * 3600:
                continue
        else:
            continue
        score = (2 if exact else 1, -pi)
        if best is None or score > best[0]:
            best = (score, kind, total)
    return (best[1], best[2]) if best else None


def cluster_coords(c):
    best = None
    for _, t in c["texts"]:
        m = COORD_RE.search(t)
        if m and (best is None or len(m.group(0)) > len(best[0])):
            best = (m.group(0), (int(m.group(1)), int(m.group(2))))
    return best[1] if best else None


def target_label(level, name):
    n = name.strip().lower()
    if "gem" in n:
        res = "Gem Mine"
    elif "gold" in n:
        res = "Gold Mine"
    elif "crop" in n:
        res = "Cropland"
    elif "lumb" in n:
        res = "Lumber Camp"
    elif "quar" in n:
        res = "Quarry"
    else:
        res = name.title().replace("Deposit", "Mine")
    return f"Level {level} {res}"


def cluster_target(c):
    for _, t in c["texts"]:
        m = TARGET_RE.search(t)
        if m:
            return target_label(m.group(1), m.group(2))
    return None


def build_clusters(passes):
    items = sorted((y, pi, t) for pi, lines in enumerate(passes) for y, t in lines)
    clusters = []
    for y, pi, t in items:
        if clusters and y - clusters[-1]["y0"] <= 24:
            clusters[-1]["ys"].append(y)
            clusters[-1]["texts"].append((pi, t))
        else:
            clusters.append({"y0": y, "ys": [y], "texts": [(pi, t)]})
    for c in clusters:
        c["y"] = sum(c["ys"]) / len(c["ys"]) / 2     # original pixels
    return clusters


def find_rows(clusters):
    """Group the screen into march rows. Returns (rows, orphan_timer_count)."""
    unit_ys = [c["y"] for c in clusters if cluster_units(c)]
    pitch = statistics.median(b - a for a, b in zip(unit_ys, unit_ys[1:])) \
        if len(unit_ys) >= 2 else 200
    reach = 0.6 * pitch

    names = {}
    for i, c in enumerate(clusters):
        key = cluster_listed(c)
        if key:
            names[i] = {"key": key, "raw": key}
    for i, c in enumerate(clusters):
        if not cluster_units(c):
            continue
        for j in range(i - 1, -1, -1):
            if c["y"] - clusters[j]["y"] > reach:
                break
            raw = cluster_name_text(clusters[j])
            if raw:
                if j not in names:
                    names[j] = {"key": None, "raw": raw}
                break

    order = sorted(names)
    rows, orphans = [], 0
    if order:
        first_y = clusters[order[0]]["y"] - 5
        orphans += sum(1 for c in clusters if c["y"] < first_y and cluster_timer(c))
    for k, i in enumerate(order):
        y0 = clusters[i]["y"] - 5
        y1 = clusters[order[k + 1]]["y"] - 5 if k + 1 < len(order) else 1e9
        inside = [c for j, c in enumerate(clusters) if j != i and y0 <= c["y"] < y1]
        timers = [(c, cluster_timer(c)) for c in inside if cluster_timer(c)]
        orphans += max(0, len(timers) - 1)
        kind = secs = None
        if timers:
            kind, secs = timers[0][1]
        coords = next((cluster_coords(c) for c in inside if cluster_coords(c)), None)
        target = next((cluster_target(c) for c in inside if cluster_target(c)), None)
        rows.append({"y": clusters[i]["y"], "key": names[i]["key"], "raw": names[i]["raw"],
                     "kind": kind, "secs": secs, "coords": coords, "target": target})
    return rows, orphans


def read_screen(img_bgr, debug=None):
    """OCR the Troops list. Returns (rows, orphan_timer_count)."""
    big = cv2.resize(img_bgr, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    variants = []
    for thr in (215, 185):
        _, mask = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)
        variants.append((f"white{thr}", cv2.bitwise_not(mask)))
    variants.append(("gray", gray))
    passes = []
    for label, v in variants:
        lines = ocr_lines(v)
        passes.append(lines)
        if debug is not None:
            debug.append(f"=== pass {label} ===")
            debug += [f"{int(y / 2):5d}  {t}" for y, t in lines]
    return find_rows(build_clusters(passes))


# ---------------------------------------------------------------- tracker
def fmt(s):
    s = max(0, int(s))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def short(secs):
    s = max(0, int(secs))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def match_slot(act, r):
    """The slot already holding this row's commander, or None."""
    if r["key"]:
        return next((s for s in act if s.key == r["key"]), None)
    norm = normalize(r["raw"])
    if len(norm) < 3:
        return None
    return next((s for s in act if s.key and not s.gatherer and
                 difflib.SequenceMatcher(None, s.norm, norm).ratio() >= 0.8), None)


def fill_slot(s, r):
    s.clear_identity()
    if r["key"]:
        s.key, s.full, s.short, s.gatherer = r["key"], r["key"], GATHERERS[r["key"]], True
    else:
        s.key, s.full, s.short, s.gatherer = "ng:" + normalize(r["raw"]), "Not a Gatherer", "", False
        s.raw, s.norm = r["raw"], normalize(r["raw"])


def assign_slot(act, r, seen):
    """Give a new commander a free slot. With none free, the commander was swapped
    into a march: take over an idle slot that is not in this scan (non-gatherer
    slots first, then the one seen least recently). A non-gatherer only replaces
    a non-gatherer. Returns (slot, replaced name) or (None, None)."""
    if not r["key"] and len(normalize(r["raw"])) < 3:
        return None, None
    s = next((s for s in act if s.key is None), None)
    if s:
        fill_slot(s, r)
        return s, None
    idle = [s for s in act if s not in seen and s.status == "idle"
            and (r["key"] or not s.gatherer)]
    if not idle:
        return None, None
    s = min(idle, key=lambda s: (s.gatherer, s.seen))
    old = s.full if s.gatherer else s.raw
    fill_slot(s, r)
    return s, old


def same_mine(a, b):
    """(coords, mine label) pairs: compare coords when both are known, else the label."""
    if a[0] and b[0]:
        return tuple(a[0]) == tuple(b[0])
    return not a[1] or not b[1] or a[1] == b[1]


def count_gather(s, now):
    """Count the gems of the gather this slot just finished, once per gather.
    Returns a RESULT line, or None."""
    s.counted = True
    key = (s.coords, s.last_target)
    if s.done and now - s.done[1] < 3600 and same_mine(s.done[0], key):
        return None   # already counted when the saved time ran out before the real timer
    s.done = (key, now)
    lvl = gem_level(s.last_target) or s.level
    if lvl in GEM_VALUE:
        add_gems(GEM_VALUE[lvl], f"{s.full} L{lvl} Gem Mine")
        return f"GEMS: {s.full} finished a Level {lvl} Gem Mine, +{GEM_VALUE[lvl]}"
    if s.last_target:
        return None   # not a gem mine
    return f"!GEMS NOT COUNTED: {s.full} finished but the mine level is unknown"


def finish_gather(s, now):
    """The march left its mine before the tracker saw the gather end (saved time
    too long, or no timer at all): count it now. A scanned timer with more than
    a minute left means the march was recalled, so nothing is counted."""
    if s.counted or s.status not in ("gathering", "ready", "update"):
        return None
    if s.status == "gathering" and not s.est and now < s.gather_due - 60:
        return None
    return count_gather(s, now)


def apply_rows(rows, n, smart=False):
    now = time.time()
    info = {"gathering": [], "walking": [], "nongather": 0, "noslot": [], "notimer": [],
            "new": False, "gems": [], "swapped": [], "smart": []}
    with lock:
        act = slots[:n]
        found = [match_slot(act, r) for r in rows]
        seen = {s for s in found if s}
        for r, s in zip(rows, found):
            s = s or match_slot(act, r)
            if s is None:
                s, old = assign_slot(act, r, seen)
                if s is None:
                    info["noslot"].append(r["key"] or r["raw"] or "?")
                    continue
                info["new"] = True
                seen.add(s)
                if old:
                    info["swapped"].append(f"March {act.index(s) + 1} {old} -> "
                                           f"{s.full if s.gatherer else s.raw}")
            s.seen = now
            if not s.gatherer:
                info["nongather"] += 1
                continue
            kind, secs = r["kind"], r["secs"]
            if kind is None:
                info["notimer"].append(s.short)
                continue
            label = r["target"]
            if kind == "walking":
                nd = now + secs
                info["walking"].append(f"{s.short} ({fmt(secs)})")
                same = s.status in ("walking", "update") and s.walk_due and abs(s.walk_due - nd) < 20
                if not same:              # a new march: it left the mine it was at
                    note = finish_gather(s, now)
                    if note:
                        info["gems"].append(note)
                if label:
                    s.last_target = label
                    if r["coords"]:
                        mine_by_coord[r["coords"]] = label
                elif s.status != "walking":
                    s.last_target = None
                s.target, s.coords = label or s.target, r["coords"]
                if same:
                    s.level = gem_level(s.target) or s.level
                    continue
                s.reset()
                s.done = None
                s.status, s.start, s.walk_due = "walking", now, nd
                s.level = gem_level(s.target)
            else:
                xy = r["coords"]
                moved = xy and s.coords and xy != s.coords
                if moved:                          # moved to another mine between scans
                    note = finish_gather(s, now)
                    if note:
                        info["gems"].append(note)
                    s.done, s.last_target = None, mine_by_coord.get(xy)
                elif smart:                        # Smart Gather: time since arrival + time left
                    arr = s.arrived or (s.walk_due if s.status == "walking" and s.walk_due
                                        and s.walk_due <= now + 30 else None)
                    lvl = s.level or gem_level(s.last_target)
                    total = now - arr + secs if arr else 0
                    if lvl in LEVELS and arr and now - arr < 3 * 3600 and 60 <= total <= 6 * 3600:
                        k = learn_time(s.key, lvl, total)
                        info["smart"].append(f"{s.short} L{lvl} measured {fmt_mmss(total)}, "
                                             f"using {fmt_mmss(smart_secs(s.key, lvl))} "
                                             f"({k} gather{'s' if k > 1 else ''})")
                s.arrived = None                   # one measurement per arrival
                s.coords = xy or s.coords
                if not s.last_target and xy in mine_by_coord:
                    s.last_target = mine_by_coord[xy]
                info["gathering"].append(s.short)
                gd = now + secs
                if s.status in ("gathering", "ready") and s.gather_due \
                        and abs(s.gather_due - gd) < 20:
                    s.est = False       # real timer agrees with the estimate
                    continue
                s.reset()               # real timer overwrites any estimate
                s.status, s.start, s.gather_due = "gathering", now, gd
    return info


def sub_parts(s):
    """Second line of a row as (before, mine, after); only `mine` can be coloured."""
    if s.key is None:
        return ("", "", "")
    if not s.gatherer:
        return (s.raw, "", "")
    xy = f" (X:{s.coords[0]} Y:{s.coords[1]})" if s.coords else ""
    if s.status == "walking":
        if s.target:
            return ("Marching to ", s.target, xy)
        return ("Marching - target not detected" + xy, "", "")
    if s.status in ("gathering", "ready"):
        post = xy + ("  - saved time" if s.est else "")
        if s.last_target:
            return ("Gathering at ", s.last_target, post)
        return ("Gem Mine level currently not detected" + post, "", "")
    if s.status == "update":
        if s.target:
            return ("Arrived at ", s.target, xy + " - scan to start the timer")
        return ("Arrived - scan to update", "", "")
    return ("", "", "")


def sub_text(s):
    return "".join(sub_parts(s))


def mine_color(mine):
    """Level 3 / 4 gem mines are shown in a soft gem red, everything else grey."""
    return GEM_RED if gem_level(mine) in (3, 4) else TEXT


def beep():
    """Short two-tone beep (plays even when Windows hides notifications during a game)."""
    try:
        import winsound
        for hz in (880, 1320):
            winsound.Beep(hz, 120)
    except Exception:
        pass


def notify(msg, sound=False):
    """Windows notification, plus a short beep when SOUND is on."""
    if sound:
        beep()
    try:
        from plyer import notification
        notification.notify(title="ROK Gem Helper", message=msg, timeout=8)
        return
    except Exception:
        pass
    try:
        import subprocess
        safe = msg.replace("'", "")
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "Add-Type -AssemblyName System.Drawing;"
              "$n = New-Object System.Windows.Forms.NotifyIcon;"
              "$n.Icon = [System.Drawing.SystemIcons]::Information;"
              "$n.BalloonTipTitle = 'ROK Gem Helper';"
              f"$n.BalloonTipText = '{safe}';"
              "$n.Visible = $true; $n.ShowBalloonTip(8000);"
              "Start-Sleep -Seconds 9; $n.Dispose()")
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                          "-Command", ps], creationflags=0x08000000)
    except Exception:
        pass


# ================================================================ overlay
class Overlay:
    """Tiny always-on-top timer window (gatherers only, short names).

    LOCKED (default): fully click-through, clicks go to the game underneath.
    UNLOCKED (F9 / move button): you can drag it; position is remembered.
    """
    POS_FILE = "overlay_pos.json"
    ALPHA = 0.88

    def __init__(self, app):
        self.app = app
        self.win = None
        self.locked = True
        self.rows = []
        self.shown = []
        self.vis = None
        self.drag = (0, 0)

    def visible(self):
        return self.win is not None

    def toggle(self):
        if self.win:
            self.win.destroy()
            self.win, self.rows, self.vis = None, [], None
        else:
            self.show()

    def show(self):
        a = self.app
        w = self.win = tk.Toplevel(a.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", self.ALPHA)
        w.configure(bg=BG)
        self.frame = tk.Frame(w, bg=BG, highlightthickness=1,
                              highlightbackground=LINE, padx=6, pady=4)
        self.frame.pack()
        self.hint = tk.Label(self.frame, text=f"DRAG ME - {key_label(a.keys['move'])} LOCKS", fg=ORANGE,
                             bg=BG, font=a.mono(7))
        self.rows = []
        for _ in range(MAX_MARCHES):
            row = tk.Frame(self.frame, bg=BG)
            n = tk.Label(row, bg=BG, fg=TEXT, font=a.mono(9), width=9, anchor="w")
            t = tk.Label(row, bg=BG, fg=WHITE, font=a.mono(9), width=8, anchor="e")
            n.pack(side="left")
            t.pack(side="left")
            self.rows.append((row, n, t))
        widgets = [w, self.frame, self.hint] + [x for r in self.rows for x in r]
        for wd in widgets:
            wd.bind("<ButtonPress-1>", self._press)
            wd.bind("<B1-Motion>", self._motion)
            wd.bind("<ButtonRelease-1>", self._release)
        self.vis = None
        with lock:
            self._layout()
        w.update_idletasks()
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        x, y = sw - w.winfo_reqwidth() - 24, 24
        try:
            with open(self.POS_FILE) as f:
                pos = json.load(f)
            x = min(max(0, int(pos["x"])), sw - 40)
            y = min(max(0, int(pos["y"])), sh - 40)
        except Exception:
            pass
        w.geometry(f"+{x}+{y}")
        w.update_idletasks()
        self.set_locked(self.locked)
        with lock:
            self.refresh(time.time(), a.tick_n)

    def _layout(self):
        """Show only the gatherer rows (at least one row so the window isn't empty)."""
        vis = [i for i, s in enumerate(slots[:self.app.n]) if s.gatherer]
        if vis == self.vis and self.win:
            return
        self.vis = vis
        self.shown = vis or [0]
        self.hint.pack_forget()
        for r in self.rows:
            r[0].pack_forget()
        if not self.locked:
            self.hint.pack()
        for i in self.shown:
            self.rows[i][0].pack(fill="x")

    def set_locked(self, locked):
        self.locked = locked
        if not self.win:
            return
        self.frame.configure(highlightbackground=LINE if locked else ORANGE)
        self.vis = None
        with lock:
            self._layout()
        self._click_through(locked)

    def _click_through(self, on):
        """Windows only: make the window ignore the mouse and never steal focus."""
        if os.name != "nt":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            st = u.GetWindowLongW(hwnd, -20)
            st |= 0x00080000 | 0x00000080 | 0x08000000   # layered, toolwindow, noactivate
            st = (st | 0x00000020) if on else (st & ~0x00000020)  # transparent to mouse
            u.SetWindowLongW(hwnd, -20, st)
        except Exception:
            pass

    def set_alpha(self, a):
        if self.win:
            self.win.attributes("-alpha", a)

    def _press(self, e):
        if not self.locked:
            self.drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _motion(self, e):
        if not self.locked:
            self.win.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def _release(self, e):
        if not self.locked:
            try:
                with open(self.POS_FILE, "w") as f:
                    json.dump({"x": self.win.winfo_x(), "y": self.win.winfo_y()}, f)
            except Exception:
                pass

    def refresh(self, now, tick_n):
        if not self.win:
            return
        self._layout()
        if not self.vis:
            row, n, t = self.rows[0]
            row.configure(bg=BG)
            n.configure(bg=BG, fg=TEXT, text="-- scan --")
            t.configure(bg=BG, text="")
            return
        cols = {"idle": TEXT, "walking": ORANGE, "update": GOLD,
                "gathering": GREEN, "ready": RED}
        blink = tick_n % 4 < 2
        for i in self.vis:
            s = slots[i]
            row, n, t = self.rows[i]
            bg = BG
            if s.status == "ready" and blink:
                bg = FLASH
            elif s.status == "update" and blink:
                bg = FLASH_UPD
            row.configure(bg=bg)
            n.configure(bg=bg, fg=cols[s.status], text=s.short[:9])
            if s.status == "walking" and s.walk_due:
                t.configure(bg=bg, text=short(s.walk_due - now), fg=ORANGE)
            elif s.status == "update":
                t.configure(bg=bg, text="SCAN", fg=GOLD)
            elif s.gather_due:
                left = s.gather_due - now
                t.configure(bg=bg, text=short(left) if left > 0 else "NOW",
                            fg=RED if s.status == "ready" else WHITE)
            else:
                t.configure(bg=bg, text="--:--", fg=TEXT)


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def http_get(url, timeout=15):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "ROK-Gem-Helper",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest_release():
    """The newest GitHub release if it is newer than this copy, else None."""
    with http_get(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest") as r:
        d = json.load(r)
    tag = d.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(APP_VERSION):
        return None
    urls = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
    if UPDATE_ASSET not in urls or UPDATE_ASSET + ".sha256" not in urls:
        return None
    return {"version": tag.lstrip("vV"), "notes": (d.get("body") or "").strip(),
            "exe": urls[UPDATE_ASSET], "sha": urls[UPDATE_ASSET + ".sha256"]}


def key_label(key):
    """'ctrl+shift+f8' -> 'Ctrl+Shift+F8' (how a hotkey is shown)."""
    return "+".join(p.upper() if len(p) == 1 or re.fullmatch(r"f\d+", p) else p.title()
                    for p in (key or "").split("+"))


def asset(name):
    """Bundled file (assets folder next to the script, or inside the exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def make_icon_image(size=256):
    """The app icon (white cube on a dark rounded square) as a PIL image."""
    from PIL import Image
    try:
        return Image.open(asset("app_icon.png")).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        return Image.new("RGBA", (size, size), (22, 24, 29, 255))


# ================================================================ GUI widgets
F = {}          # font families, filled in by init_fonts()
_FONTS = {}
_IMG = {}


def init_fonts():
    fams = set(tkfont.families())
    pick = lambda *names: next((n for n in names if n in fams), names[-1])
    F["ui"] = pick("Segoe UI", "Helvetica")
    F["semi"] = pick("Segoe UI Semibold", "Segoe UI", "Helvetica")
    F["icon"] = pick("Segoe Fluent Icons", "Segoe MDL2 Assets", "")
    F["mono"] = pick("Consolas", "Cascadia Mono", "Courier New", "Courier")


def font(size=10, kind="ui"):
    return (F[kind], size)


def icon_font(size=11):
    return (F["icon"], size)


def glyph(name):
    """Icon character, or nothing when Windows' icon font isn't there."""
    return IC[name] if F["icon"] else ""


def measure(ft, text):
    f = _FONTS.get(ft)
    if f is None:
        f = _FONTS[ft] = tkfont.Font(font=ft)
    return f.measure(text)


def rr(w, h, r, fill, outline=None):
    """Anti-aliased rounded rectangle as a PhotoImage (cached). Callers keep a
    reference, so clearing the cache never blanks a widget."""
    w, h = max(1, int(w)), max(1, int(h))
    key = (w, h, r, fill, outline)
    im = _IMG.get(key)
    if im is None:
        from PIL import Image, ImageDraw, ImageTk
        if len(_IMG) > 800:
            _IMG.clear()
        k = 3
        big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle(
            [0, 0, w * k - 1, h * k - 1], radius=max(0, min(r, w // 2, h // 2)) * k,
            fill=fill, outline=outline, width=k if outline else 0)
        im = _IMG[key] = ImageTk.PhotoImage(big.resize((w, h), Image.LANCZOS))
    return im


def recolor(w, old, new):
    """Swap one background colour for another in a widget tree (row flashing)."""
    try:
        if w.cget("bg") == old:
            w.configure(bg=new)
    except tk.TclError:
        pass
    for c in w.winfo_children():
        recolor(c, old, new)


class Tip:
    """Small hover tooltip; text can be a string or a function returning one."""

    def __init__(self, w, text):
        self.w, self.text, self.win, self.job = w, text, None, None
        w.bind("<Enter>", self._enter, add="+")
        w.bind("<Leave>", self._leave, add="+")
        w.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, e):
        self.job = self.w.after(400, self._show)

    def _leave(self, e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.win:
            self.win.destroy()
            self.win = None

    def _show(self):
        self.job = None
        text = self.text() if callable(self.text) else self.text
        if not text or not self.w.winfo_viewable():
            return
        t = self.win = tk.Toplevel(self.w)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=text, bg=FIELD_HI, fg=WHITE, font=font(9), padx=9, pady=5,
                 justify="left", wraplength=320).pack()
        t.geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 6}")


class Box(tk.Canvas):
    """Rounded card. Put children in .body; the height follows the content."""

    def __init__(self, parent, fill, radius=12, pad=(16, 14), outline=None):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, width=10, height=1)
        self.fill, self.radius, self.outline = fill, radius, outline
        self.px, self.py = pad
        self.body = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.px, self.py, window=self.body, anchor="nw")
        self._size = None
        self.body.bind("<Configure>", self._fit, add="+")
        self.bind("<Configure>", self._fit, add="+")

    def _fit(self, e=None):
        w = self.winfo_width()
        h = self.body.winfo_reqheight() + 2 * self.py
        if w > 2 * self.px:
            self.itemconfigure(self._win, width=w - 2 * self.px)
        if int(float(self.cget("height"))) != h:
            self.configure(height=h)
        if w > 1 and (w, h, self.fill) != self._size:
            self._size = (w, h, self.fill)
            self._img = rr(w, h, self.radius, self.fill, self.outline)
            self.delete("bg")
            self.create_image(0, 0, image=self._img, anchor="nw", tags="bg")
            self.tag_lower("bg")

    def set_fill(self, fill):
        if fill != self.fill:
            old, self.fill = self.fill, fill
            recolor(self.body, old, fill)
            self._fit()


class Pill(tk.Canvas):
    """Rounded button / chip with an optional icon. Without cmd it is just a label."""

    def __init__(self, parent, text="", icon="", cmd=None, fill=FIELD, fg=WHITE, hover=None,
                 h=34, padx=14, size=10, width=None, radius=None, icon_fg=None, anchor="center",
                 tip=None):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, height=h,
                         cursor="hand2" if cmd else "")
        self.text, self.icon, self.cmd = text, icon, cmd
        self.fill, self.fg, self.hover, self.icon_fg = fill, fg, hover, icon_fg
        self.h, self.padx, self.size, self.fixed_w, self.anchor = h, padx, size, width, anchor
        self.radius = h // 2 if radius is None else radius
        self._over = False
        if cmd:
            self.bind("<Enter>", lambda e: self._hov(True))
            self.bind("<Leave>", lambda e: self._hov(False))
            self.bind("<ButtonRelease-1>", self._click)
        if tip:
            Tip(self, tip)
        self.draw()

    def _hov(self, on):
        self._over = on
        self.draw()

    def _click(self, e):
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.h and self.cmd:
            self.cmd()

    def set(self, **kw):
        changed = False
        for k, v in kw.items():
            if getattr(self, k) != v:
                setattr(self, k, v)
                changed = True
        if changed:
            self.draw()

    def draw(self):
        ft, ift = font(self.size, "semi"), icon_font(self.size + 1)
        tw = measure(ft, self.text) if self.text else 0
        iw = measure(ift, self.icon) if self.icon else 0
        gap = 8 if self.icon and self.text else 0
        w = self.fixed_w or tw + iw + gap + 2 * self.padx
        if int(float(self.cget("width"))) != w:
            self.configure(width=w)
        fill = self.hover if self._over and self.hover else self.fill
        self.delete("all")
        self._img = rr(w, self.h, self.radius, fill)
        self.create_image(0, 0, image=self._img, anchor="nw")
        x = self.padx if self.anchor == "w" else (w - tw - iw - gap) / 2
        if self.icon:
            self.create_text(x, self.h / 2 + 1, text=self.icon, font=ift, anchor="w",
                             fill=self.icon_fg or self.fg)
            x += iw + gap
        if self.text:
            self.create_text(x, self.h / 2, text=self.text, font=ft, anchor="w", fill=self.fg)


class Seg(tk.Canvas):
    """Segmented switch: a rounded track with one highlighted option (Off | On, 15s | 30s ...)."""

    def __init__(self, parent, options, value, cmd, seg_w=None, h=32, size=9, colors=None, tip=None):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, height=h,
                         cursor="hand2")
        self.opts, self.value, self.cmd, self.h, self.size = options, value, cmd, h, size
        self.colors = colors or {}
        self.enabled = True
        self.sw = seg_w or max(measure(font(size, "semi"), lbl) for _, lbl in options) + 26
        self.w = self.sw * len(options) + 6
        self.configure(width=self.w)
        self.bind("<ButtonRelease-1>", self._click)
        if tip:
            Tip(self, tip)
        self.draw()

    def draw(self):
        self.delete("all")
        self._imgs = [rr(self.w, self.h, 9, FIELD)]
        self.create_image(0, 0, image=self._imgs[0], anchor="nw")
        ft = font(self.size, "semi")
        for i, (v, lbl) in enumerate(self.opts):
            x, sel = 3 + i * self.sw, v == self.value
            if sel:
                im = rr(self.sw, self.h - 6, 7,
                        self.colors.get(v, ACCENT) if self.enabled else SEL_OFF)
                self._imgs.append(im)
                self.create_image(x, 3, image=im, anchor="nw")
            self.create_text(x + self.sw / 2, self.h / 2, text=lbl, font=ft,
                             fill=WHITE if sel else TEXT if self.enabled else MUTED)

    def _click(self, e):
        i = int((e.x - 3) // self.sw)
        if self.enabled and 0 <= i < len(self.opts) and 0 <= e.y <= self.h:
            self.cmd(self.opts[i][0])

    def set(self, value=None, enabled=None):
        nv = self.value if value is None else value
        ne = self.enabled if enabled is None else enabled
        if (nv, ne) != (self.value, self.enabled):
            self.value, self.enabled = nv, ne
            self.configure(cursor="hand2" if ne else "")
            self.draw()


class Bar(tk.Canvas):
    """Thin rounded progress bar."""

    def __init__(self, parent, w=150, h=6):
        super().__init__(parent, bg=parent["bg"], width=w, height=h, highlightthickness=0, bd=0)
        self.w, self.h, self.state = w, h, None

    def set(self, frac, color):
        fw = round(self.w * min(1.0, max(0.0, frac))) if color else 0
        if (fw, color) == self.state:
            return
        self.state = (fw, color)
        self.delete("all")
        self._imgs = [rr(self.w, self.h, 3, FIELD)]
        self.create_image(0, 0, image=self._imgs[0], anchor="nw")
        if fw:
            self._imgs.append(rr(max(fw, self.h), self.h, 3, color))
            self.create_image(0, 0, image=self._imgs[1], anchor="nw")


class Scroll(tk.Frame):
    """Vertical scroll area with a slim rounded scrollbar; content goes in .body."""

    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        self.bar = tk.Canvas(self, bg=bg, width=6, highlightthickness=0, bd=0)
        self.bar.pack(side="right", fill="y", padx=(8, 0))
        self.cv.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.cv, bg=bg)
        self._win = self.cv.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._region())
        self.cv.bind("<Configure>", self._resize)
        self.cv.configure(yscrollcommand=self._thumb)
        self.bar.bind("<ButtonPress-1>", self._drag)
        self.bar.bind("<B1-Motion>", self._drag)

    def _resize(self, e):
        self.cv.itemconfigure(self._win, width=e.width)
        self._region()

    def _region(self):
        self.cv.configure(scrollregion=(0, 0, self.cv.winfo_width(), self.body.winfo_reqheight()))
        if self.body.winfo_reqheight() <= self.cv.winfo_height():
            self.cv.yview_moveto(0)

    def _thumb(self, lo, hi):
        lo, hi = float(lo), float(hi)
        h = self.bar.winfo_height()
        self.bar.delete("all")
        if hi - lo < 0.999 and h > 10:
            th = max(30, (hi - lo) * h)
            y = lo * (h - th) / max(0.001, 1 - (hi - lo))
            self._bimg = rr(6, th, 3, FIELD_HI)
            self.bar.create_image(0, y, image=self._bimg, anchor="nw")

    def _drag(self, e):
        self.cv.yview_moveto(max(0.0, e.y / max(1, self.bar.winfo_height()) - 0.05))

    def wheel(self, e):
        if self.body.winfo_reqheight() > self.cv.winfo_height():
            self.cv.yview_scroll(int(-e.delta / 120) * 2, "units")

    def scroll_to(self, w):
        self.update_idletasks()
        total = max(1, self.body.winfo_reqheight())
        self.cv.yview_moveto((w.winfo_rooty() - self.body.winfo_rooty()) / total)


class TimeEntry(tk.Entry):
    """MM:SS box that shows a grey 'MM:SS' hint while empty."""
    PH = "MM:SS"

    def __init__(self, parent, font):
        super().__init__(parent, width=6, bg=FIELD, fg=WHITE, insertbackground=WHITE,
                         relief="flat", bd=0, font=font, justify="center", highlightthickness=0,
                         disabledbackground=FIELD, disabledforeground=GRAY)
        self.ph = False
        self.smart = False       # value put in by Smart Gather (teal), not typed
        self.shown = ""
        self._hint()
        self.bind("<FocusIn>", self._in)
        self.bind("<FocusOut>", self._out)
        self.bind("<KeyRelease>", self._typed)

    def _typed(self, e):
        self.mark_ok()
        if self.smart and self.get() != self.shown:   # edited by hand: it's yours now
            self.smart = False
            self.configure(fg=WHITE)

    def _hint(self):
        self.delete(0, "end")
        self.insert(0, self.PH)
        self.configure(fg=GRAY)
        self.ph = True
        self.smart = False

    def _in(self, e):
        if self.ph:
            self.delete(0, "end")
            self.configure(fg=WHITE)
            self.ph = False

    def _out(self, e):
        if not self.get().strip():
            self._hint()

    def value(self):
        return "" if self.ph else self.get().strip()

    def set_value(self, text, smart=False):
        st = str(self.cget("state"))
        self.configure(state="normal")
        if text:
            self.delete(0, "end")
            self.insert(0, text)
            self.configure(fg=TEAL if smart else WHITE)
            self.ph, self.smart, self.shown = False, smart, text
        else:
            self._hint()
        self.set_locked(st == "disabled")

    def set_locked(self, locked):
        self.configure(state="disabled" if locked else "normal",
                       disabledforeground=GRAY if self.ph else TEAL if self.smart else GREEN)

    def mark_bad(self):
        self.master.itemconfigure("bg", image=self.master.bad)

    def mark_ok(self):
        self.master.itemconfigure("bg", image=self.master.ok)


class Field(tk.Canvas):
    """Rounded box around a TimeEntry (turns red when the time is invalid)."""

    def __init__(self, parent, w=70, h=34):
        super().__init__(parent, bg=parent["bg"], width=w, height=h, highlightthickness=0, bd=0)
        self.ok, self.bad = rr(w, h, 8, FIELD), rr(w, h, 8, FIELD, outline=RED)
        self.create_image(0, 0, image=self.ok, anchor="nw", tags="bg")
        self.entry = TimeEntry(self, font(11, "semi"))
        self.create_window(w // 2, h // 2, window=self.entry, width=w - 14, height=h - 12)


# march row look per status: (icon, colour, chip text)
LOOK = {"idle": ("clock", MUTED, "Idle"), "walking": ("walk", ORANGE, "Marching"),
        "update": ("sync", GOLD, "Scan now"), "gathering": ("timer", GREEN, "Gathering"),
        "ready": ("warn", RED, "Resend!"), "empty": ("unknown", MUTED, "Empty"),
        "skip": ("minus", MUTED, "Skipped")}


class App:
    def __init__(self, root, n, lead, region, hotkeys_ok, demo=False):
        self.root, self.region, self.hotkeys_ok = root, region, hotkeys_ok
        self.q = queue.Queue()
        self.scanning = False
        self.tick_n = 0
        self.n = max(1, min(MAX_MARCHES, n))
        self.setup_locked = False
        init_fonts()

        root.title("ROK Gem Helper")
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(make_icon_image(64))
            root.iconphoto(True, self._icon)
        except Exception:
            pass
        root.configure(bg=BG)
        root.geometry("1280x900")
        root.minsize(1120, 620)

        self.demo = demo
        cfg = {} if demo else load_settings()     # command-line options win over saved ones
        self.lead = tk.IntVar(value=lead if lead is not None else int(cfg.get("lead", 30)))
        self.sound_on = bool(cfg.get("sound", False))
        self.smart_on = bool(cfg.get("smart", True))
        self.collapsed = set(cfg.get("collapsed", [])) if isinstance(cfg.get("collapsed"), list) else set()
        saved = cfg.get("hotkeys") if isinstance(cfg.get("hotkeys"), dict) else {}
        self.keys = {a: str(saved.get(a) or d).lower() for a, d in DEFAULT_KEYS.items()}
        self.capturing = None
        if not demo:
            self.hotkeys_ok = self.register_hotkeys()
        if region is None and isinstance(cfg.get("region"), list) and len(cfg["region"]) == 4:
            self.region = [int(v) for v in cfg["region"]]
        self.overlay = Overlay(self)
        self.picker = None
        self._tvis = None
        self.tray = None
        self.update_rel, self.updating = None, False
        root.protocol("WM_DELETE_WINDOW", self.quit_app)
        if not demo:
            self.load_slots()
            load_times()
            load_smart()
            load_gems()
        self.build()
        self.refresh_setup()
        if demo:
            self.load_demo()
        else:
            self.load_state()
            if cfg.get("overlay"):
                self.toggle_overlay()
            threading.Thread(target=self.check_update, daemon=True).start()
            root.after(8000, self.remove_old_exe)
        self.tick()

    # ---------- small helpers
    def mono(self, size=9):
        """Overlay font (fixed width, so the timers don't jump)."""
        return (F["mono"], size, "bold")

    def label(self, parent, text="", fg=TEXT, size=10, kind="ui", **kw):
        return tk.Label(parent, text=text, fg=fg, bg=parent["bg"], font=font(size, kind), **kw)

    def icon(self, parent, name, fg=TEXT, size=12, **kw):
        return tk.Label(parent, text=glyph(name), fg=fg, bg=parent["bg"], font=icon_font(size), **kw)

    def info(self, parent, tip):
        lb = self.icon(parent, "info", fg=MUTED, size=10)
        Tip(lb, tip)
        return lb

    def logo(self, size, rounded=False):
        from PIL import Image, ImageTk
        try:
            im = make_icon_image(size) if rounded else \
                Image.open(asset("logo.png")).convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception:
            im = make_icon_image(size)
        return ImageTk.PhotoImage(im)

    # ---------- layout
    def build(self):
        side = tk.Frame(self.root, bg=SIDEBAR, width=236)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.build_sidebar(side)
        self.build_header(main)
        self.build_update_bar(main)
        self.build_log(main)
        self.scroll = Scroll(main, BG)
        self.scroll.pack(fill="both", expand=True, padx=(28, 10), pady=(0, 14))
        self.root.bind_all("<MouseWheel>", self.scroll.wheel)
        self.sec = {}
        self.build_marches(self.scroll.body)
        self.build_times(self.scroll.body)
        self.build_settings(self.scroll.body)
        for key in self.collapsed & set(self.sec):
            self.toggle_section(key, save=False)

    def build_sidebar(self, sd):
        top = tk.Frame(sd, bg=SIDEBAR)
        top.pack(fill="x", padx=18, pady=(20, 14))
        self._logo_sm = self.logo(30)
        tk.Label(top, image=self._logo_sm, bg=SIDEBAR).pack(side="left")
        self.label(top, "ROK Gem Helper", WHITE, 12, "semi").pack(side="left", padx=(10, 0))

        st = tk.Frame(sd, bg=SIDEBAR)
        st.pack(fill="x", padx=18, pady=(0, 16))
        ok = self.hotkeys_ok
        Pill(st, "Live" if ok else "Hotkeys off", h=24, size=8, padx=10, fill=FIELD,
             fg=GREEN if ok else RED,
             tip=(lambda: " / ".join(key_label(k) for k in self.keys.values())
                  + " work everywhere, even in the game") if ok else
             "Hotkeys could not be registered - run the app as administrator").pack(side="left")
        Pill(st, time.strftime("%d %b %Y"), h=24, size=8, padx=10, fill=FIELD, fg=TEXT
             ).pack(side="left", padx=(6, 0))
        Pill(st, f"v{APP_VERSION}", h=24, size=8, padx=10, fill=FIELD, fg=MUTED
             ).pack(side="left", padx=(6, 0))

        for key, ic, name in (("marches", "walk", "Marches"), ("times", "timer", "Gather Times"),
                              ("settings", "settings", "Settings")):
            Pill(sd, name, glyph(ic), lambda k=key: self.goto(k), fill=SIDEBAR, hover=FIELD,
                 fg=WHITE, icon_fg=TEXT, h=38, size=10, width=204, radius=9, anchor="w",
                 padx=12).pack(padx=16, pady=1, anchor="w")

        foot = tk.Frame(sd, bg=SIDEBAR)
        foot.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
        gem = Box(foot, GROUP, radius=12, pad=(14, 12))
        gem.pack(fill="x", pady=(0, 12))
        gb = gem.body
        for row, name in ((0, "Total gems"), (2, "Today")):
            self.label(gb, "◆", GEM_RED, 9).grid(row=row, column=0, sticky="w")
            self.label(gb, name, MUTED, 9, "semi").grid(row=row, column=1, sticky="w", padx=(6, 0))
        self.gem_total = self.label(gb, "", WHITE, 16, "semi")
        self.gem_total.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self.gem_day = self.label(gb, "", WHITE, 13, "semi")
        self.gem_day.grid(row=3, column=0, columnspan=2, sticky="w")
        Tip(gem, "Gem Mine level x = x*10 gems per finished gather (L1 10 ... L4 40).\n"
                 "Commander talents and buffs are not counted. Today resets at midnight.")
        keys = tk.Frame(foot, bg=SIDEBAR)
        keys.pack(fill="x", pady=(0, 10))
        self.key_chips = {}
        for action, what in HOTKEY_ACTIONS:
            self.key_chips[action] = Pill(keys, f"{key_label(self.keys[action])} {what}", h=24,
                                          size=8, padx=8, fill=FIELD, fg=TEXT)
            self.key_chips[action].pack(side="left", padx=(0, 5))
        Pill(foot, "Donate", glyph("heart"), self.donate, fill="#3a1f2c", hover="#4a2638",
             fg=WHITE, icon_fg=PINK, h=34, size=9, width=204, radius=9,
             tip="Like the app? Support it on PayPal").pack(anchor="w", pady=(0, 10))
        self.label(foot, "Found a bug? Contact", MUTED, 8).pack(anchor="w")
        bug = self.label(foot, f"@{DISCORD_NAME} on Discord", "#8ea1f0", 9, "semi", cursor="hand2")
        bug.pack(anchor="w")
        bug.bind("<Button-1>", lambda e: self.copy_discord())
        Tip(bug, "Click to copy the Discord name")
        self.build_changelog(sd)       # after the footer, so it only takes the space left

    # ---------- hotkeys
    def register_hotkeys(self):
        """(Re)bind the global hotkeys. A key that can't be bound goes back to its
        default; False when the keyboard hook isn't available at all."""
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            return False
        for action in self.keys:
            for key in (self.keys[action], DEFAULT_KEYS[action]):
                try:
                    keyboard.add_hotkey(key, lambda a=action: self.q.put((a,)))
                    self.keys[action] = key
                    break
                except Exception:
                    continue
        return True

    def capture_key(self, action):
        if not self.hotkeys_ok:
            self.set_result("!HOTKEYS OFF: run the app as administrator to use and change hotkeys")
            return
        waiting = self.capturing is not None
        self.capturing = action
        self.paint_keys()
        self.set_result(f"HOTKEY: press the new key for {dict(HOTKEY_ACTIONS)[action]} (Esc cancels)")
        if not waiting:
            threading.Thread(target=self._read_key, daemon=True).start()

    def _read_key(self):
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()      # the old keys must not fire while choosing
            key = keyboard.read_hotkey(suppress=False)
        except Exception:
            key = None
        self.q.put(("hotkey", key))

    def set_key(self, key):
        action, self.capturing = self.capturing, None
        names = dict(HOTKEY_ACTIONS)
        key = (key or "").lower()
        other = next((a for a, k in self.keys.items() if k == key and a != action), None)
        if not action or not key or key == "esc":
            msg = "HOTKEY: unchanged"
        elif all(part in MODIFIERS for part in key.split("+")):
            msg = f"!HOTKEY: {key_label(key)} alone can't be a hotkey - add another key"
        elif other:
            msg = f"!HOTKEY: {key_label(key)} is already used for {names[other]}"
        else:
            self.keys[action] = key
            msg = f"HOTKEY: {names[action]} is now {key_label(key)}"
        self.register_hotkeys()
        if action and self.keys[action] != key and msg.startswith("HOTKEY: " + names[action]):
            msg = f"!HOTKEY: {key_label(key)} can't be used - {names[action]} stays " \
                  f"{key_label(self.keys[action])}"
        self.paint_keys()
        self.save_settings()
        self.set_result(msg)

    def reset_keys(self):
        self.keys = dict(DEFAULT_KEYS)
        if self.hotkeys_ok and self.capturing is None:
            self.register_hotkeys()
        self.paint_keys()
        self.save_settings()
        self.set_result("HOTKEY: back to F8 Scan, F9 Move, F10 Clear")

    def paint_keys(self):
        for action, what in HOTKEY_ACTIONS:
            busy = action == self.capturing
            self.key_btns[action].set(text="Press a key..." if busy else
                                      f"{what}  {key_label(self.keys[action])}",
                                      fill=ACCENT if busy else FIELD,
                                      hover=ACCENT_HI if busy else FIELD_HI)
            self.key_chips[action].set(text=f"{key_label(self.keys[action])} {what}")

    def donate(self):
        import webbrowser
        webbrowser.open(DONATE_URL)
        self.set_result("THANK YOU: the PayPal page opened in your browser")

    def copy_discord(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(DISCORD_NAME)
        self.set_result(f"COPIED: {DISCORD_NAME} - paste it in Discord to report a bug")

    def build_changelog(self, sd):
        hd = tk.Frame(sd, bg=SIDEBAR)
        hd.pack(fill="x", padx=20, pady=(22, 8))
        self.label(hd, "WHAT'S NEW", MUTED, 8, "semi").pack(side="left")
        box = self.cl_box = tk.Frame(sd, bg=SIDEBAR)
        box.pack(fill="both", expand=True, padx=(20, 14))
        box.pack_propagate(False)            # the list never pushes the footer away
        self.cl_lines, self.cl_fit = [], None
        for n, (ver, date, items) in enumerate(CHANGELOG):
            top = tk.Frame(box, bg=SIDEBAR)
            self.label(top, f"v{ver}", WHITE if ver == APP_VERSION else TEXT, 10, "semi").pack(side="left")
            self.label(top, date, MUTED, 8).pack(side="left", padx=(8, 0), pady=(2, 0))
            self.cl_lines.append((top, (12 if n else 0, 4), True))
            for it in items:
                row = tk.Frame(box, bg=SIDEBAR)
                self.label(row, "•", ACCENT, 9).pack(side="left", anchor="n")
                self.label(row, it, TEXT, 9, wraplength=172, justify="left", anchor="w"
                           ).pack(side="left", padx=(6, 0), fill="x")
                self.cl_lines.append((row, (1, 1), False))
        box.bind("<Configure>", lambda e: self.fit_changelog())

    def fit_changelog(self):
        """Show only lines that fit completely; the rest are hidden, not cut in half.
        A version heading is only shown together with its first line."""
        avail = self.cl_box.winfo_height()
        if avail == self.cl_fit:
            return
        self.cl_fit = avail
        for w, _, _ in self.cl_lines:
            w.pack_forget()
        used = 0
        for i, (w, pady, head) in enumerate(self.cl_lines):
            h = w.winfo_reqheight() + sum(pady)
            if head and i + 1 < len(self.cl_lines):
                nxt, npady, _ = self.cl_lines[i + 1]
                h_need = h + nxt.winfo_reqheight() + sum(npady)
            else:
                h_need = h
            if used + h_need > avail:
                break
            w.pack(fill="x", pady=pady)
            used += h

    def build_header(self, m):
        h = tk.Frame(m, bg=BG)
        h.pack(fill="x", padx=28, pady=(20, 16))
        self._logo_hd = self.logo(46, rounded=True)
        tk.Label(h, image=self._logo_hd, bg=BG).pack(side="left")
        t = tk.Frame(h, bg=BG)
        t.pack(side="left", padx=(14, 0))
        self.label(t, "ROK Gem Helper", WHITE, 19, "semi").pack(anchor="w")
        self.label(t, "Gem march timers for Rise of Kingdoms", MUTED, 9).pack(anchor="w")

        self.scan_btn = Pill(h, "Scan", glyph("scan"), self.start_scan, fill="#f3f4f6",
                             fg="#111317", hover="#ffffff", h=44, size=11, padx=24,
                             tip=lambda: f"Read the Troops list on screen ({key_label(self.keys['scan'])})")
        self.scan_btn.pack(side="right")
        btn = dict(h=42, width=42, fill=FIELD, hover=FIELD_HI, size=11, fg=WHITE)
        self.tray_btn = Pill(h, "", glyph("tray"), self.minimize_to_tray,
                             tip="Hide to the system tray (timers keep running)", **btn)
        self.ov_btn = Pill(h, "", glyph("overlay"), self.toggle_overlay,
                           tip="Overlay on / off", **btn)
        self.move_btn = Pill(h, "", glyph("move"), self.toggle_move,
                             tip=lambda: "Unlock the overlay to drag it, click again to lock "
                                         f"({key_label(self.keys['move'])})", **btn)
        self.clear_btn = Pill(h, "", glyph("trash"), self.clear,
                              tip=lambda: f"Clear all timers ({key_label(self.keys['clear'])})",
                              **dict(btn, fill=RED, hover="#ef6a6e"))
        for b in (self.tray_btn, self.ov_btn, self.move_btn, self.clear_btn):
            b.pack(side="right", padx=(0, 10))

    def build_update_bar(self, m):
        self.upd_box = Box(m, "#152238", radius=14, pad=(18, 10), outline="#24406b")
        ub = self.upd_box.body
        self.icon(ub, "sync", ACCENT, 13).pack(side="left")
        self.upd_text = self.label(ub, "", WHITE, 10, "semi", anchor="w")
        self.upd_text.pack(side="left", padx=(10, 0))
        Tip(self.upd_text, lambda: self.update_rel and self.update_rel["notes"])
        Pill(ub, "Later", "", lambda: self.upd_box.pack_forget(), h=32, size=9, fill=FIELD,
             hover=FIELD_HI).pack(side="right")
        self.upd_go = Pill(ub, "Update now", "", self.start_update, h=32, size=9, fill=ACCENT,
                           hover=ACCENT_HI)
        self.upd_go.pack(side="right", padx=(0, 8))

    def build_log(self, m):
        box = Box(m, CARD, radius=14, pad=(18, 12), outline=BORDER)
        box.pack(side="bottom", fill="x", padx=(28, 24), pady=(0, 18))
        head = tk.Frame(box.body, bg=CARD)
        head.pack(fill="x")
        self.icon(head, "log", TEXT, 11).pack(side="left")
        self.label(head, "Log", WHITE, 10, "semi").pack(side="left", padx=(8, 0))
        self.result_txt = tk.Text(box.body, width=100, height=1, bg=CARD, bd=0,
                                  highlightthickness=0, wrap="word", cursor="arrow",
                                  font=font(10), takefocus=0, padx=0, pady=0)
        self.result_txt.tag_configure("head", foreground=GREEN, font=font(10, "semi"))
        self.result_txt.tag_configure("body", foreground=WHITE)
        self.result_txt.tag_configure("err", foreground=RED)
        self.result_txt.pack(fill="x", pady=(6, 0))
        self.set_result("READY: open the Troops list in the game and press Scan "
                        f"({key_label(self.keys['scan'])})")

    def section(self, parent, key, ic, title, tip=None):
        box = Box(parent, CARD, radius=14, pad=(20, 16), outline=BORDER)
        box.pack(fill="x", pady=(0, 16))
        head = tk.Frame(box.body, bg=CARD)
        head.pack(fill="x")
        self.icon(head, ic, TEXT, 12).pack(side="left")
        self.label(head, title, WHITE, 11, "semi").pack(side="left", padx=(10, 6))
        if tip:
            self.info(head, tip).pack(side="left")
        chev = Pill(head, "", glyph("up"), lambda: self.toggle_section(key), fill=CARD,
                    hover=FIELD, fg=TEXT, h=30, width=30, size=9)
        chev.pack(side="right")
        body = tk.Frame(box.body, bg=CARD)
        body.pack(fill="x", pady=(14, 0))
        self.sec[key] = {"box": box, "body": body, "chev": chev}
        return head, body

    def toggle_section(self, key, save=True):
        s = self.sec[key]
        if s["body"].winfo_manager():
            s["body"].pack_forget()
            s["chev"].set(icon=glyph("down"))
            self.collapsed.add(key)
        else:
            s["body"].pack(fill="x", pady=(14, 0))
            s["chev"].set(icon=glyph("up"))
            self.collapsed.discard(key)
        if save:
            self.save_settings()

    def goto(self, key):
        if key in self.collapsed:
            self.toggle_section(key)
        self.scroll.scroll_to(self.sec[key]["box"])

    def build_marches(self, parent):
        _, body = self.section(parent, "marches", "walk", "Marches",
                               "One row per march, read from the Troops list. Scan while marching "
                               "and again once gathering; the overlay shows the same timers.")
        self.rows = []
        for i in range(MAX_MARCHES):
            box = Box(body, GROUP, radius=10, pad=(16, 10))
            b = box.body
            w = {"box": box}
            w["idx"] = self.label(b, f"M{i + 1}", MUTED, 9, "semi", width=3, anchor="w")
            w["icon"] = self.icon(b, "clock", MUTED, 14, width=2)
            mid = tk.Frame(b, bg=GROUP)
            w["name"] = self.label(mid, "", WHITE, 11, "semi", anchor="w")
            w["name"].pack(anchor="w")
            sub = tk.Frame(mid, bg=GROUP)
            sub.pack(anchor="w")
            w["subl"] = [self.label(sub, "", TEXT, 9, padx=0) for _ in range(3)]
            for lb in w["subl"]:
                lb.pack(side="left")
            w["chip"] = Pill(b, "", h=26, size=9, width=104, fill=FIELD, fg=MUTED)
            w["time"] = self.label(b, "", WHITE, 13, "semi", width=9, anchor="e")
            w["bar"] = Bar(b, 150, 6)
            w["idx"].grid(row=0, column=0, sticky="w")
            w["icon"].grid(row=0, column=1, sticky="w", padx=(0, 8))
            mid.grid(row=0, column=2, sticky="we")
            w["chip"].grid(row=0, column=3, padx=(10, 6))
            w["time"].grid(row=0, column=4, sticky="e", padx=(0, 16))
            w["bar"].grid(row=0, column=5)
            b.columnconfigure(2, weight=1)
            self.rows.append(w)

    def build_times(self, parent):
        head, body = self.section(parent, "times", "timer", "Gather Times",
                                  "How long each commander takes to clear a Gem Mine of each "
                                  "level, as MM:SS. When a march arrives at a mine its time "
                                  "starts by itself. Lock a row to keep its times.")
        self.smart_seg = Seg(head, [(False, "Off"), (True, "On")], self.smart_on, self.set_smart,
                             colors={False: SEL_OFF}, h=30, seg_w=48)
        self.smart_seg.pack(side="right", padx=(0, 12))
        self.info(head, "Smart Gather learns each commander's time per level from your scans "
                        "(scan while marching, then again once gathering) and fills EMPTY boxes "
                        "in teal. Typed times are never replaced.").pack(side="right", padx=(0, 8))
        self.label(head, "Smart Gather", TEXT, 9, "semi").pack(side="right", padx=(0, 6))
        self.icon(head, "smart", TEAL, 11).pack(side="right", padx=(0, 6))
        self.t_empty = self.label(body, "Scan first - detected gatherers appear here.", MUTED, 9,
                                  anchor="w")
        self.t_empty.pack(fill="x")
        self.t_holder = tk.Frame(body, bg=CARD)
        self.t_holder.pack(fill="x")
        for c in (0, 1):
            self.t_holder.columnconfigure(c, weight=1, uniform="t")
        self.trows = []
        for i in range(MAX_MARCHES):
            box = Box(self.t_holder, GROUP, radius=10, pad=(16, 12))
            b = box.body
            top = tk.Frame(b, bg=GROUP)
            top.pack(fill="x")
            self.label(top, f"M{i + 1}", MUTED, 9, "semi").pack(side="left")
            nm = self.label(top, "", WHITE, 10, "semi")
            nm.pack(side="left", padx=(8, 0))
            btn = Pill(top, "", glyph("unlock"), lambda i=i: self.toggle_lock(i), h=30, width=30,
                       size=9, fill=FIELD, hover=FIELD_HI, fg=WHITE,
                       tip="Lock: keep these times (saved). Unlock to edit.")
            btn.pack(side="right")
            ents = tk.Frame(b, bg=GROUP)
            ents.pack(fill="x", pady=(8, 0))
            ent = {}
            for L in LEVELS:
                cell = tk.Frame(ents, bg=GROUP)
                cell.pack(side="left", padx=(0, 8))
                self.label(cell, f"L{L}", MUTED, 8, "semi").pack(anchor="w")
                fld = Field(cell)
                fld.pack()
                ent[L] = fld.entry
            self.trows.append({"box": box, "name": nm, "btn": btn, "ent": ent,
                               "key": None, "locked": False})

    def build_settings(self, parent):
        _, body = self.section(parent, "settings", "settings", "Settings")
        grp = Box(body, GROUP, radius=10, pad=(18, 14))
        grp.pack(fill="x")
        g = grp.body
        for c in (0, 1):
            g.columnconfigure(c, weight=1, uniform="s")

        def item(row, col, ic, name, tip):
            f = tk.Frame(g, bg=GROUP)
            f.grid(row=row, column=col, sticky="we", pady=8, padx=(0, 18) if col == 0 else 0)
            self.icon(f, ic, ACCENT, 12).pack(side="left")
            self.label(f, name, WHITE, 10, "semi", width=10, anchor="w").pack(side="left", padx=(10, 0))
            self.info(f, tip).pack(side="left", padx=(0, 12))
            ctl = tk.Frame(f, bg=GROUP)
            ctl.pack(side="left", fill="x", expand=True)
            return ctl

        c = item(0, 0, "people", "Marches",
                 "How many marches you have. Commanders fill in from the first scan, then the "
                 "count locks; Reset clears the slots.")
        self.n_seg = Seg(c, [(i, str(i)) for i in range(1, MAX_MARCHES + 1)], self.n, self.set_n,
                         seg_w=27, h=32)
        self.n_seg.pack(side="left")
        self.reset_btn = Pill(c, "Reset", glyph("reset"), self.reset_slots, h=32, size=9, padx=10,
                              fill=FIELD, hover=FIELD_HI, tip="Clear the commander slots and scan again")
        self.setup_note = self.label(c, "", MUTED, 8)

        c = item(0, 1, "area", "Scan area",
                 "Set: drag a box around the Troops list, scans then read only that part "
                 "(faster, fewer misreads). Full: read the whole screen.")
        self.area_btn = Pill(c, "Set", glyph("area"), self.pick_area, h=32, size=9, fill=FIELD,
                             hover=FIELD_HI)
        self.area_btn.pack(side="left")
        self.full_btn = Pill(c, "Full", glyph("full"), lambda: self.set_region(None), h=32,
                             size=9, fill=FIELD, hover=FIELD_HI)
        self.full_btn.pack(side="left", padx=(6, 10))
        self.area_lbl = self.label(c, "", MUTED, 8)
        self.area_lbl.pack(side="left")
        self.paint_area()

        c = item(1, 0, "timer", "Lead",
                 "How many seconds before a gather ends the first alert comes; "
                 "a second one follows at half of that.")
        self.lead_seg = Seg(c, [(15, "15s"), (30, "30s"), (60, "60s"), (120, "2m")],
                            self.lead.get(), self.set_lead, seg_w=50, h=32)
        self.lead_seg.pack(side="left")
        self.set_lead(self.lead.get())

        c = item(1, 1, "sound", "Sound",
                 "Short beep with every alert. Windows hides notifications while a "
                 "full-screen game runs; the beep still plays.")
        self.sound_seg = Seg(c, [(False, "Off"), (True, "On")], self.sound_on, self.set_sound,
                             colors={False: SEL_OFF}, seg_w=50, h=32)
        self.sound_seg.pack(side="left")

        c = item(2, 0, "keyboard", "Hotkeys",
                 "Click a button, then press the key (or key combination) you want for it. "
                 "Esc cancels. The keys work everywhere, even while the game is focused.")
        self.key_btns = {}
        for action, what in HOTKEY_ACTIONS:
            b = Pill(c, "", "", lambda a=action: self.capture_key(a), h=32, size=9, padx=12,
                     fill=FIELD, hover=FIELD_HI)
            b.pack(side="left", padx=(0, 6))
            self.key_btns[action] = b
        Pill(c, "", glyph("reset"), self.reset_keys, h=32, width=32, size=9, fill=FIELD,
             hover=FIELD_HI, tip="Back to F8 / F9 / F10").pack(side="left")
        self.paint_keys()

    # ---------- gather times
    def gather_secs(self, i, level):
        """Seconds to clear a gem mine of this level for slot i (None if not set)."""
        if level not in LEVELS:
            return None
        return parse_mmss(self.trows[i]["ent"][level].value()) or None

    def set_row_locked(self, i, locked):
        row = self.trows[i]
        row["locked"] = locked
        for e in row["ent"].values():
            e.set_locked(locked)
        row["btn"].set(icon=glyph("lock" if locked else "unlock"),
                       fill=ACCENT if locked else FIELD, hover=ACCENT_HI if locked else FIELD_HI)

    def toggle_lock(self, i):
        row, s = self.trows[i], slots[i]
        if not s.gatherer:
            return
        if row["locked"]:
            self.set_row_locked(i, False)
            if s.key in GATHER_TIMES:
                GATHER_TIMES[s.key]["locked"] = False
                save_times(f"UNLOCKED {s.full}")
            self.set_result(f"UNLOCKED: {s.full} - edit the times, then lock again")
            return
        times, bad = {}, []
        for L, e in row["ent"].items():
            v = e.value()
            if not v:
                continue
            secs = parse_mmss(v)
            if secs:
                times[L] = secs
            else:
                bad.append(f"L{L}")
                e.mark_bad()
        if bad:
            self.set_result(f"!INVALID TIME: {s.full} {', '.join(bad)} - use MM:SS, e.g. 25:30")
            return
        if not times:
            self.set_result(f"!NOTHING TO LOCK: enter at least one time for {s.full}")
            return
        for L, e in row["ent"].items():        # show cleaned-up MM:SS
            e.set_value(fmt_mmss(times[L]) if L in times else "")
        GATHER_TIMES[s.key] = {"locked": True, "times": times}
        self.set_row_locked(i, True)
        txt = ", ".join(f"L{L} {fmt_mmss(v)}" for L, v in sorted(times.items()))
        save_times(f"LOCKED {s.full}: {txt}")
        self.set_result(f"LOCKED: {s.full} saved ({txt})")

    def refresh_times(self):
        """Show a box for every detected gatherer; load its saved times when it appears."""
        vis = []
        for i, s in enumerate(slots[:self.n]):
            row = self.trows[i]
            if s.gatherer:
                vis.append(i)
                if row["key"] != s.key:
                    row["key"] = s.key
                    prof = GATHER_TIMES.get(s.key)
                    for L, e in row["ent"].items():
                        e.mark_ok()
                        e.set_value(fmt_mmss(prof["times"][L])
                                    if prof and L in prof["times"] else "")
                    self.set_row_locked(i, bool(prof and prof["locked"] and prof["times"]))
                    row["name"].configure(text=s.full)
                self.smart_fill(i, s.key)
            else:
                row["key"] = None
        if vis != self._tvis:
            self._tvis = vis
            for r in self.trows:
                r["box"].grid_forget()
            for k, i in enumerate(vis):
                self.trows[i]["box"].grid(row=k // 2, column=k % 2, sticky="we", pady=(0, 12),
                                          padx=(0, 6) if k % 2 == 0 else (6, 0))
            if vis:
                self.t_empty.pack_forget()
            else:
                self.t_empty.pack(fill="x", before=self.t_holder)

    def smart_fill(self, i, key):
        """Smart Gather: learned times go into empty boxes (teal); a typed time is never replaced."""
        try:
            focus = self.root.focus_get()
        except Exception:
            focus = None
        for L, e in self.trows[i]["ent"].items():
            if e is focus or not (e.smart or not e.value()):
                continue
            secs = smart_secs(key, L) if self.smart_on else None
            text = fmt_mmss(secs) if secs else ""
            if text != e.value() or e.smart != bool(text):
                e.set_value(text, smart=True)

    # ---------- setup (march count + locked slots)
    def refresh_setup(self):
        self.n_seg.set(self.n, not self.setup_locked)
        if self.setup_locked:
            self.reset_btn.pack(side="left", padx=(10, 0))
            self.setup_note.pack_forget()
        else:
            self.reset_btn.pack_forget()
        for i, w in enumerate(self.rows):
            if i < self.n:
                w["box"].pack(fill="x", pady=(0, 8))
            else:
                w["box"].pack_forget()

    def set_n(self, v):
        if self.setup_locked:
            return
        self.n = v
        self.refresh_setup()
        self.save_slots()

    def reset_slots(self):
        with lock:
            for s in slots:
                s.clear_identity()
            mine_by_coord.clear()
        self.setup_locked = False
        self.refresh_setup()
        self.set_result("RESET: slots cleared - scan again")
        self.save_slots()
        self.save_state()

    def save_slots(self):
        try:
            with lock:
                data = {"n": self.n, "locked": self.setup_locked,
                        "slots": [{"key": s.key, "raw": s.raw} if s.key else None
                                  for s in slots]}
            with open(SLOTS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_slots(self):
        try:
            with open(SLOTS_FILE) as f:
                data = json.load(f)
            self.n = max(1, min(MAX_MARCHES, int(data.get("n", self.n))))
            with lock:
                for s, d in zip(slots, data.get("slots", [])):
                    if not d or not d.get("key"):
                        continue
                    if d["key"] in GATHERERS:
                        s.key, s.full, s.short, s.gatherer = d["key"], d["key"], GATHERERS[d["key"]], True
                    elif d["key"].startswith("ng:"):
                        s.key, s.full, s.gatherer = d["key"], "Not a Gatherer", False
                        s.raw, s.norm = d.get("raw", ""), normalize(d.get("raw", ""))
            self.setup_locked = bool(data.get("locked")) and any(s.key for s in slots)
        except Exception:
            pass

    # ---------- actions
    def set_lead(self, v):
        self.lead.set(v)
        self.lead_seg.set(v)
        self.save_settings()

    def set_sound(self, on):
        self.sound_on = on
        self.paint_sound()
        self.save_settings()
        if on:
            threading.Thread(target=beep, daemon=True).start()   # let them hear it
        self.set_result("SOUND: on - a short beep plays with every alert" if on
                        else "SOUND: off - notifications only")

    def set_smart(self, on):
        self.smart_on = on
        self.paint_smart()
        self.save_settings()
        self.set_result("SMART GATHER: on - gather times are learned from your scans and fill "
                        "empty boxes" if on else "SMART GATHER: off - only your own times are used")

    def paint_smart(self):
        self.smart_seg.set(self.smart_on)

    def paint_sound(self):
        self.sound_seg.set(self.sound_on)

    def paint_area(self):
        r = self.region
        self.area_btn.set(fill=ACCENT if r else FIELD, hover=ACCENT_HI if r else FIELD_HI)
        self.full_btn.set(fill=FIELD if r else ACCENT, hover=FIELD_HI if r else ACCENT_HI)
        self.area_lbl.configure(text=f"{r[2]}x{r[3]} at {r[0]},{r[1]}" if r else "whole screen")

    def set_region(self, region):
        self.region = region
        self.paint_area()
        self.save_settings()
        self.set_result(f"SCAN AREA: {region[2]}x{region[3]} at {region[0]},{region[1]} - "
                        "scans read only this part of the screen" if region
                        else "SCAN AREA: whole screen")


    def pick_area(self):
        """Drag a box around the Troops list; scans then read only that part of the screen."""
        if self.picker:
            return
        try:
            import mss
            with mss.mss() as sct:
                mon = next((m for m in sct.monitors[1:] if m["left"] == 0 and m["top"] == 0),
                           sct.monitors[1])
        except Exception as e:
            self.set_result(f"!SCAN AREA FAILED: {e}")
            return
        self.root.attributes("-alpha", 0.0)
        self.overlay.set_alpha(0.0)
        w = self.picker = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.35)
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        w.geometry(f"{sw}x{sh}+0+0")
        c = tk.Canvas(w, bg="black", highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        c.create_text(sw // 2, 60, fill=WHITE, font=font(16, "semi"),
                      text="DRAG A BOX AROUND THE TROOPS LIST  -  ESC OR RIGHT CLICK CANCELS")
        start = [0, 0]

        def press(e):
            start[:] = e.x, e.y
            c.delete("sel")
            c.create_rectangle(e.x, e.y, e.x, e.y, outline=GOLD, width=3, tags="sel")

        def motion(e):
            c.coords("sel", start[0], start[1], e.x, e.y)

        def release(e):
            x0, x1 = sorted((start[0], e.x))
            y0, y1 = sorted((start[1], e.y))
            if x1 - x0 < 40 or y1 - y0 < 40:
                return                      # just a click: keep picking
            fx, fy = mon["width"] / sw, mon["height"] / sh   # Windows display scaling
            finish([mon["left"] + round(x0 * fx), mon["top"] + round(y0 * fy),
                    round((x1 - x0) * fx), round((y1 - y0) * fy)])

        def finish(region):
            w.destroy()
            self.picker = None
            self.root.attributes("-alpha", 1.0)
            self.overlay.set_alpha(Overlay.ALPHA)
            if region:
                self.set_region(region)

        c.bind("<ButtonPress-1>", press)
        c.bind("<B1-Motion>", motion)
        c.bind("<ButtonRelease-1>", release)
        c.bind("<Button-3>", lambda e: finish(None))
        w.bind("<Escape>", lambda e: finish(None))
        w.focus_force()

    def toggle_overlay(self):
        self.overlay.toggle()
        on = self.overlay.visible()
        self.ov_btn.set(fill=ACCENT if on else FIELD, hover=ACCENT_HI if on else FIELD_HI)
        if not on:
            self.move_btn.set(fill=FIELD, hover=FIELD_HI)
        self.save_settings()

    def toggle_move(self):
        """Unlock the overlay for dragging, or lock it back (click-through)."""
        if not self.overlay.visible():
            self.overlay.show()
            self.ov_btn.set(fill=ACCENT, hover=ACCENT_HI)
            self.overlay.set_locked(False)
            self.save_settings()
        else:
            self.overlay.set_locked(not self.overlay.locked)
        free = not self.overlay.locked
        self.move_btn.set(fill=ACCENT if free else FIELD, hover=ACCENT_HI if free else FIELD_HI)

    def clear(self):
        with lock:
            for s in slots:
                s.reset()
        self.set_result("CLEARED: all timers reset")
        self.save_state()

    def set_result(self, text, color=None):
        """Errors (lines starting with '!', or color=RED) show red; otherwise
        the heading before ':' is green and the explanation is white."""
        t = self.result_txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            nl = "\n" if i < len(lines) - 1 else ""
            if color == RED or ln.startswith("!"):
                t.insert("end", ln.lstrip("!").strip() + nl, "err")
            elif ":" in ln:
                head, body = ln.split(":", 1)
                t.insert("end", head + ":", "head")
                t.insert("end", body + nl, "body")
            else:
                t.insert("end", ln + nl, "body")
        t.configure(height=sum(max(1, -(-len(l) // 100)) for l in lines), state="disabled")

    def start_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.scan_btn.set(text="Scanning")
        self.set_result("SCANNING: reading the Troops list...")
        threading.Thread(target=self.scan_worker, args=(self.n,), daemon=True).start()

    def scan_worker(self, n):
        try:
            ev = threading.Event()          # hide our own windows so the scan can't read them
            self.q.put(("hide", ev))
            ev.wait(2)
            time.sleep(0.25)
            img = grab(self.region)
            dbg = []
            rows, orphans = read_screen(img, dbg)
            self.q.put(("show",))
            if orphans or not rows:
                try:
                    cv2.imwrite("scan_debug.png", img)
                    with open("scan_debug.txt", "w", encoding="utf-8") as f:
                        f.write("\n".join(dbg))
                except Exception:
                    pass
            info = apply_rows(rows, n, self.smart_on)
            lines = []
            if info["gathering"]:
                lines.append("GATHERING: " + ", ".join(info["gathering"]))
            if info["walking"]:
                lines.append("MARCHING: " + ", ".join(info["walking"]))
            if info["nongather"]:
                lines.append(f"NOT A GATHERER: {info['nongather']} march(es)")
            if info["notimer"]:
                lines.append("NO TIMER VISIBLE: " + ", ".join(info["notimer"]))
            for sw in info["swapped"]:
                lines.append("SWAPPED: " + sw)
            lines += info["gems"]
            lines += ["SMART GATHER: " + x for x in info["smart"]]
            with lock:
                empty = sum(1 for s in slots[:n] if s.key is None)
            if empty:
                lines.append(f"SLOTS: {empty} still empty - scroll the list and scan again")
            if info["noslot"]:
                lines.append("!NO FREE SLOT (raise HOW MANY): " + ", ".join(info["noslot"]))
            if orphans:
                lines.append(f"!{orphans} timer(s) with unreadable name skipped "
                             "(saved scan_debug.png / .txt)")
            if not rows:
                lines.insert(0, "!NOTHING FOUND - is the Troops list open?" +
                             (" Is it inside the SCAN AREA?" if self.region else ""))
            self.q.put(("msg", "\n".join(lines), None))
            self.q.put(("lock_if_filled",))
            self.q.put(("save",))
        except Exception as e:
            self.q.put(("show",))
            self.q.put(("msg", f"!SCAN FAILED: {e}", RED))
        finally:
            self.q.put(("done",))

    def save_state(self):
        now = time.time()
        try:
            with lock:
                data = [{
                    "march": i + 1, "key": s.key, "commander": s.full, "short": s.short,
                    "gatherer": s.gatherer, "status": s.status,
                    "target": s.target, "gathering_target": s.last_target, "estimated": s.est,
                    "arrive_in_s": int(s.walk_due - now) if s.walk_due else None,
                    "due_epoch": s.gather_due,
                    "gather_left_s": int(s.gather_due - now) if s.gather_due else None,
                    "walk_due": s.walk_due, "start": s.start,
                    "coords": list(s.coords) if s.coords else None, "level": s.level,
                    "counted": s.counted, "alert2": s.alert2, "arrived": s.arrived,
                    "done": {"coords": list(s.done[0][0]) if s.done[0][0] else None,
                             "mine": s.done[0][1], "at": s.done[1]} if s.done else None,
                } for i, s in enumerate(slots[:self.n]) if s.key]
            with open(STATE_FILE, "w") as f:
                json.dump({"updated": now, "marches": data}, f, indent=2)
        except Exception:
            pass

    def load_state(self):
        """Pick the timers up again after a restart. A timer that ran out while the
        app was closed goes through its normal end on the first tick (gems counted,
        no alert, row cleared); a row waiting for a scan is dropped after 30 min."""
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                marches = json.load(f).get("marches", [])
        except Exception:
            return
        now = time.time()
        with lock:
            for d in marches:
                i = int(d.get("march") or 0) - 1
                if not 0 <= i < self.n or not d.get("key"):
                    continue
                s, st = slots[i], d.get("status")
                walk, due, level = d.get("walk_due"), d.get("due_epoch"), d.get("level")
                if not s.gatherer or d["key"] != s.key:
                    continue
                if not (st in ("walking", "update") and walk or st in ("gathering", "ready") and due):
                    continue
                saved = GATHER_TIMES.get(s.key, {}).get("times", {}).get(level)
                if (st == "update" or st == "walking" and not saved) and walk < now - 1800:
                    continue
                s.reset()
                s.status, s.walk_due, s.gather_due = st, walk, due
                s.start = d.get("start") or now
                s.target, s.last_target = d.get("target"), d.get("gathering_target")
                s.coords = tuple(d["coords"]) if d.get("coords") else None
                s.level, s.est = level, bool(d.get("estimated"))
                s.counted, s.alert2 = bool(d.get("counted")), bool(d.get("alert2"))
                s.arrived = d.get("arrived")
                dn = d.get("done")
                if dn:
                    s.done = ((tuple(dn["coords"]) if dn.get("coords") else None, dn.get("mine")),
                              dn.get("at") or 0)

    def save_settings(self):
        if self.demo:
            return
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"lead": self.lead.get(), "sound": self.sound_on, "smart": self.smart_on,
                           "region": list(self.region) if self.region else None,
                           "overlay": self.overlay.visible(),
                           "collapsed": sorted(self.collapsed),
                           "hotkeys": self.keys}, f, indent=2)
        except Exception:
            pass

    # ---------- main loop
    def drain(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                return
            k = item[0]
            if k == "scan":
                self.start_scan()
            elif k == "clear":
                self.clear()
            elif k == "move":
                self.toggle_move()
            elif k == "tray_show":
                self.show_from_tray()
            elif k == "tray_overlay":
                self.toggle_overlay()
            elif k == "tray_exit":
                self.quit_app()
                return
            elif k == "hide":
                self.root.attributes("-alpha", 0.0)
                self.overlay.set_alpha(0.0)
                item[1].set()
            elif k == "show":
                self.root.attributes("-alpha", 1.0)
                self.overlay.set_alpha(Overlay.ALPHA)
            elif k == "msg":
                self.set_result(item[1], item[2])
            elif k == "lock_if_filled":
                with lock:
                    filled = any(s.key for s in slots)
                if filled and not self.setup_locked:
                    self.setup_locked = True
                    self.refresh_setup()
            elif k == "save":
                self.save_state()
                self.save_slots()
            elif k == "hotkey":
                self.set_key(item[1])
            elif k == "update":
                self.show_update(item[1])
            elif k == "restart":
                self.restart(item[1])
                return
            elif k == "update_failed":
                self.updating = False
                self.upd_go.set(text="Update now")
                self.set_result(f"!UPDATE FAILED: {item[1]} - you can try again or keep using this version")
            elif k == "done":
                self.scanning = False
                self.scan_btn.set(text="Scan")

    def tick(self):
        self.drain()
        self.tick_n += 1
        now, lead = time.time(), self.lead.get()
        changed = False
        with lock:
            self.refresh_times()      # first, so saved times are there for arrivals
            for i, s in enumerate(slots):
                if not s.gatherer:
                    continue
                est = " (est.)" if s.est else ""
                if s.status == "gathering" and now >= s.gather_due - lead:
                    s.status = "ready"
                    changed = True
                    s.alert2 = now >= s.gather_due - lead / 2   # already past halfway: skip 2nd
                    if now < s.gather_due:                      # no alert for one already over
                        self.toast(f"{s.short}: {round(s.gather_due - now)}s left{est} - "
                                   "get ready to resend!")
                if s.status == "ready":
                    if not s.alert2 and now >= s.gather_due - lead / 2:
                        s.alert2 = True
                        changed = True
                        if now < s.gather_due:
                            self.toast(f"{s.short}: {round(s.gather_due - now)}s left{est} - "
                                       "resend now!")
                    if not s.counted and now >= s.gather_due:
                        note = count_gather(s, now)
                        if note:
                            self.set_result(note)
                        changed = True
                    if now > s.gather_due + 300:
                        s.reset()
                        changed = True
                elif s.status == "walking" and s.walk_due and now >= s.walk_due:
                    secs = self.gather_secs(i, s.level) if i < self.n else None
                    s.arrived = s.walk_due
                    if secs:              # arrived: start the saved gather time, no rescan needed
                        s.start, s.gather_due = s.walk_due, s.walk_due + secs
                        s.walk_due, s.status, s.est = None, "gathering", True
                    else:
                        s.status = "update"   # arrived: flag it, NO notification
                    changed = True
            for s, w in zip(slots, self.rows):
                self.paint_row(s, w, now)
            self.overlay.refresh(now, self.tick_n)
        if self.tray:
            self.keep_overlay()
        roll_day()
        self.gem_total.configure(text=f"{GEMS['total']:,}")
        self.gem_day.configure(text=f"{GEMS['daily']:,}")
        if changed:
            self.save_state()
        self.root.after(200, self.tick)

    # ---------- system tray
    def minimize_to_tray(self):
        if self.tray:
            return
        try:
            import pystray
            import pystray._win32  # noqa: F401  (makes PyInstaller bundle the Windows backend)
        except Exception as e:
            if os.name != "nt" and isinstance(e, (ImportError, ValueError)) and "pystray" in str(e) and "_win32" in str(e):
                pass  # not Windows: the Windows backend is irrelevant here
            else:
                self.set_result(f"!TRAY UNAVAILABLE: could not load pystray ({type(e).__name__}: {e}). "
                                "Run  pip install pystray  and rebuild the exe")
                return
        q = self.q
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda icon, item: q.put(("tray_show",)), default=True),
            pystray.MenuItem("Overlay", lambda icon, item: q.put(("tray_overlay",)),
                             checked=lambda item: self.overlay.visible()),
            pystray.MenuItem("Exit", lambda icon, item: q.put(("tray_exit",))))
        try:
            self.tray = pystray.Icon("ROKGemHelper", make_icon_image(64),
                                     "ROK Gem Helper", menu)
            self.tray.run_detached()
        except Exception as e:
            self.tray = None
            self.set_result(f"!TRAY FAILED: {e}")
            return
        self.root.withdraw()
        self.keep_overlay()

    def keep_overlay(self):
        """The overlay must stay visible while the main window is in the tray."""
        ov = self.overlay
        try:
            if ov.win and ov.win.state() == "withdrawn":
                ov.win.deiconify()
                ov.win.attributes("-topmost", True)
                ov._click_through(ov.locked)
        except Exception:
            pass

    def stop_tray(self):
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
            self.tray = None

    def show_from_tray(self):
        self.stop_tray()
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def quit_app(self):
        self.save_state()
        self.stop_tray()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------- updates
    def check_update(self):
        try:
            rel = latest_release()
        except Exception:
            return              # offline or GitHub unreachable: check again next start
        if rel:
            self.q.put(("update", rel))

    def show_update(self, rel):
        self.update_rel = rel
        first = rel["notes"].splitlines()[0].strip("#*- ") if rel["notes"] else ""
        self.upd_text.configure(text=f"Update available: v{rel['version']}"
                                     + (f"  -  {first[:90]}" if first else ""))
        if not self.upd_box.winfo_manager():
            self.upd_box.pack(fill="x", padx=(28, 24), pady=(0, 14), before=self.scroll)

    def start_update(self):
        if self.updating or not self.update_rel:
            return
        if not getattr(sys, "frozen", False):
            self.set_result("!UPDATE: only the exe updates itself - you are running the .py script")
            return
        self.updating = True
        self.upd_go.set(text="Updating...")
        threading.Thread(target=self.update_worker, args=(self.update_rel,), daemon=True).start()

    def update_worker(self, rel):
        """Download the new exe, check its SHA-256, swap it in and restart.
        Windows can't overwrite a running exe but can rename it, so the old one
        becomes .old (deleted on the next start)."""
        import hashlib
        exe = sys.executable
        new, old = exe + ".new", exe + ".old"
        try:
            with http_get(rel["sha"]) as r:
                want = r.read().decode().split()[0].lower()
            h, got, step = hashlib.sha256(), 0, -1
            with http_get(rel["exe"], 60) as r, open(new, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    pct = got * 100 // total if total else 0
                    if pct // 10 != step:
                        step = pct // 10
                        self.q.put(("msg", f"UPDATE: downloading v{rel['version']} - {pct}%", None))
            if h.hexdigest() != want:
                os.remove(new)
                raise ValueError("the download was damaged (checksum mismatch)")
            try:
                os.remove(old)
            except OSError:
                pass
            os.replace(exe, old)
            try:
                os.replace(new, exe)
            except OSError:
                os.replace(old, exe)            # put the old one back
                raise
            self.q.put(("restart", exe))
        except Exception as e:
            self.q.put(("update_failed", str(e)))

    def restart(self, exe):
        import subprocess
        self.set_result(f"UPDATE: installed - restarting")
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")   # start as a fresh app
        subprocess.Popen([exe], cwd=os.getcwd(), env=env, close_fds=True)
        self.quit_app()

    def remove_old_exe(self):
        if getattr(sys, "frozen", False):
            try:
                os.remove(sys.executable + ".old")
            except OSError:
                pass

    def toast(self, msg):
        threading.Thread(target=notify, args=(msg, self.sound_on), daemon=True).start()

    def set_sub(self, w, parts):
        pre, mine, post = parts
        for lb, text, fg in zip(w["subl"], (pre, mine, post), (TEXT, mine_color(mine), TEXT)):
            if lb.cget("text") != text or lb.cget("fg") != fg:
                lb.configure(text=text, fg=fg)

    def paint_row(self, s, w, now):
        blink = self.tick_n % 4 < 2
        w["box"].set_fill(FLASH if s.status == "ready" and blink else
                          FLASH_UPD if s.status == "update" and blink else GROUP)
        if s.key is None:
            look, name, sub = "empty", "Not scanned yet", ("", "", "")
        elif not s.gatherer:
            look, name, sub = "skip", "Not a Gatherer", (s.raw, "", "")
        else:
            look, name, sub = s.status, s.full, sub_parts(s)
        ic, col, chip = LOOK[look]
        w["icon"].configure(text=glyph(ic), fg=col)
        w["name"].configure(text=name, fg=WHITE if s.gatherer else MUTED)
        w["chip"].set(text=chip, fg=col)
        self.set_sub(w, sub)
        frac, text, tcol = None, "", WHITE
        if s.gatherer and s.status == "walking" and s.walk_due:
            left = s.walk_due - now
            frac, text = left / max(1.0, s.walk_due - s.start), fmt(left)
        elif s.gatherer and s.status == "update":
            text, tcol = "SCAN", GOLD
        elif s.gatherer and s.gather_due:
            left = s.gather_due - now
            frac = left / max(1.0, s.gather_due - s.start)
            text, tcol = fmt(left) if left > 0 else "NOW", RED if s.status == "ready" else WHITE
        elif s.gatherer:
            text, tcol = "--:--:--", MUTED
        w["time"].configure(text=text, fg=tcol)
        w["bar"].set(frac or 0, col if frac is not None else None)

    def load_demo(self):
        now = time.time()
        demo = [("Seondeok", "gathering", 1094, "Level 3 Gem Mine", (214, 718)),
                ("Cleopatra VII", "gathering", 613, "Level 2 Gem Mine", (164, 629)),
                ("Pepin III", "walking", 278, "Level 3 Gem Mine", (154, 869)),
                ("Ishida Mitsunari", "update", None, "Level 3 Gem Mine", None),
                ("Queen Tamar of Georgia", "ready", 20, "Level 4 Gem Mine", (103, 668))]
        with lock:
            for s, (key, st, secs, tgt, xy) in zip(slots, demo):
                s.key, s.full, s.short, s.gatherer = key, key, GATHERERS[key], True
                s.status, s.last_target, s.target, s.coords = st, tgt, tgt, xy
                if st == "walking":
                    s.walk_due, s.start = now + secs, now - 100
                elif secs is not None:
                    s.gather_due, s.start = now + secs, now - 200
            slots[5].key, slots[5].raw, slots[5].norm = "ng:charlesmartel", "Charles Martel", "charlesmartel"
            slots[5].full = "Not a Gatherer"
        GEMS.update(total=20856, day=time.strftime('%Y-%m-%d'), daily=340)
        SMART["Cleopatra VII"] = {3: [1500, 1530, 1512]}
        self.n = 7
        self.setup_locked = True
        self.refresh_setup()
        self.refresh_times()
        for L, v in zip(LEVELS, ("30:00", "27:30", "25:00", "22:15")):
            self.trows[0]["ent"][L].set_value(v)
        self.set_row_locked(0, True)
        for L, v in zip((1, 2), ("32:10", "29:40")):
            self.trows[1]["ent"][L].set_value(v)
        self.set_result("GATHERING: Seondeok, Cleopatra\nMARCHING: Pepin (00:04:38)\n"
                        "NOT A GATHERER: 1 march(es)\nSLOTS: 1 still empty - scroll the list and scan again\n!NO FREE SLOT (raise HOW MANY): example error", None)


# ================================================================ main
DATA_FILES = ("overlay_pos.json", "scan_debug.png", "scan_debug.txt")


def use_data_dir():
    """Work inside a 'data' folder next to the exe, so the exe's folder stays tidy.
    Files an older version left next to the exe are moved in."""
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    data = os.path.join(base, "data")
    os.makedirs(data, exist_ok=True)
    for name in os.listdir(base):
        if name.startswith("march_") and name.endswith((".json", ".log")) or name in DATA_FILES:
            if not os.path.exists(os.path.join(data, name)):
                try:
                    os.replace(os.path.join(base, name), os.path.join(data, name))
                except OSError:
                    pass
    os.chdir(data)


def main():
    global STATE_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument("--marches", type=int, default=5, help="how many marches you have (1-7)")
    ap.add_argument("--lead", type=int, help="seconds (default: saved setting, else 30)")
    ap.add_argument("--region", nargs=4, type=int, metavar=("L", "T", "W", "H"))
    ap.add_argument("--test-image")
    ap.add_argument("--tesseract", default=r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    ap.add_argument("--state-file", default=STATE_FILE)
    ap.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--snap", help=argparse.SUPPRESS)
    a = ap.parse_args()
    STATE_FILE = a.state_file

    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    local = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
    if os.path.exists(local):
        pytesseract.pytesseract.tesseract_cmd = local
    elif os.path.exists(a.tesseract):
        pytesseract.pytesseract.tesseract_cmd = a.tesseract

    if a.test_image:
        rows, orph = read_screen(cv2.imread(a.test_image))
        info = apply_rows(rows, MAX_MARCHES)
        for i, r in enumerate(rows):
            s = match_slot(slots, r)
            who = s.full if s else "?"
            t = f"{r['kind']} {fmt(r['secs'])}" if r["kind"] else "no timer"
            print(f"{who:<24} {t:<20} {sub_text(s) if s else ''}")
        print("Unassigned timers:", orph)
        return

    use_data_dir()

    root = tk.Tk()
    app_box = {}
    app = App(root, a.marches, a.lead, a.region, hotkeys_ok=a.demo, demo=a.demo)
    app_box["app"] = app
    app.save_state()

    if a.snap:
        def snap():
            from PIL import ImageGrab
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(a.snap + "_main.png")
            ov = app.overlay
            ov.show()
            ov.set_locked(True)
            root.update()
            ov.win.geometry("+1000+60")
            root.update()
            x, y, w_, h_ = ov.win.winfo_x(), ov.win.winfo_y(), ov.win.winfo_width(), ov.win.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w_, y + h_)).resize((w_ * 3, h_ * 3)).save(a.snap + "_overlay.png")
            root.destroy()
        root.after(1200, snap)
    root.mainloop()


if __name__ == "__main__":
    main()
