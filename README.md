# ROK Gem Helper

Gem march timers for **Rise of Kingdoms** (PC).

When you farm gems by sending a march from one mine straight to the next, the
game never tells you when a gather is done. ROK Gem Helper reads the Troops list
on your screen, keeps a timer for every march, and alerts you (Windows
notification, optional beep, flashing overlay) shortly before each gather ends.

## Install

1. Install **Tesseract OCR** (reads the text on screen):
   https://github.com/UB-Mannheim/tesseract/wiki - keep the default folder.
2. Download `ROK-Gem-Helper.exe` from the
   [latest release](../../releases/latest) and put it in its own folder.
3. Double-click it. Windows may ask for administrator rights (needed for the
   F8 / F9 / F10 hotkeys while the game is focused).

The app updates itself: when a new version is out it shows
**Update available** - click **Update now**.

## Use

1. Settings > Marches: pick how many marches you have.
2. Open the Troops list in the game and press **F8** (or click **Scan**).
3. Scan again after sending marches out, and once they start gathering.
4. Optional: Settings > Scan area > **Set** and drag a box around the Troops
   list for faster scans; turn on the **overlay** to keep timers on top of the game.

| Key | Action |
| --- | --- |
| F8  | Scan the Troops list |
| F9  | Unlock / lock the overlay for moving |
| F10 | Clear all timers |

**Gather Times**: type how long each commander takes per Gem Mine level, or let
**Smart Gather** learn it from your scans. A march's gather timer then starts by
itself when it arrives.

**Gems**: level x Gem Mine = x*10 gems per finished gather. Commander talents
and buffs are not counted.

All data (gems, times, settings) is stored next to the exe.

---
Made by @ChanaMasala on Discord.
