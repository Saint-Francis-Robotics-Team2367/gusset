#!/bin/bash
# =============================================================================
#  Install Gusset (Mac) - double-click this file.
#  Copies Gusset into Fusion's own add-ins folder, so it starts by itself with
#  Fusion. Safe to run again: your settings, remembered choices and logs stay.
#  If macOS says it "can't be opened", right-click this file > Open > Open.
# =============================================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/Gusset"
DEST="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/Gusset"
KEEP=(gusset_config.json gusset_state.json team_settings_draft.json)
say() { printf '%s\n' "$*"; }
fail() { say ""; say "  Problem: $*"; say "  Nothing else was changed. Press Return to close."; read -r _; exit 1; }

say ""; say "  Installing Gusset..."; say ""
[ -f "$SRC/Gusset.py" ] || fail "can't find the Gusset folder next to this installer. Unzip the whole download first."
VERSION=$(sed -n 's/^VERSION *= *"\(.*\)".*/\1/p' "$SRC/config.py" | head -1)

if pgrep -x "Autodesk Fusion" >/dev/null 2>&1 || pgrep -x "Autodesk Fusion 360" >/dev/null 2>&1; then
  say "  Fusion is open. Save your work and QUIT Fusion (Command-Q), then press Return."
  read -r _
  if pgrep -x "Autodesk Fusion" >/dev/null 2>&1 || pgrep -x "Autodesk Fusion 360" >/dev/null 2>&1; then fail "Fusion is still open."; fi
fi

mkdir -p "$DEST" || fail "couldn't make $DEST"

# Move this computer's files over from an older 'FRC Plugins' copy (only if the new place has none).
for OLD in "$HOME/FRC Plugins/Gusset" "$HOME/Documents/FRC Plugins/Gusset"; do
  if [ -f "$OLD/Gusset.py" ] && [ "$OLD" != "$DEST" ]; then
    say "  Found an older copy in: $OLD"
    for f in "${KEEP[@]}"; do
      [ -f "$OLD/$f" ] && [ ! -f "$DEST/$f" ] && cp "$OLD/$f" "$DEST/$f" && say "    kept $f"
    done
    [ -d "$OLD/cache" ] && [ ! -d "$DEST/cache" ] && cp -R "$OLD/cache" "$DEST/cache" && say "    kept the COTS picture cache"
    mv "$OLD" "$OLD (old copy - safe to delete)" && say "    renamed the old copy so Fusion stops loading it"
  fi
done

# Copy the new code, never touching this computer's own files.
cd "$SRC" || fail "can't open $SRC"
find . -type d -name __pycache__ -prune -o -type f -print | while IFS= read -r f; do
  rel="${f#./}"
  case "$rel" in
    gusset_config.json|gusset_state.json|team_settings_draft.json|logs/*|cache/*) continue ;;
  esac
  mkdir -p "$DEST/$(dirname "$rel")"
  cp "$f" "$DEST/$rel" || exit 9
done || fail "couldn't copy the files into $DEST"

xattr -dr com.apple.quarantine "$DEST" 2>/dev/null   # files from the internet: let Fusion read them
say ""; say "  Done! Gusset $VERSION is installed in:"; say "    $DEST"
say ""; say "  Open Fusion - the GUSSET tab appears by itself."
say "  (If it doesn't: UTILITIES > ADD-INS > Scripts and Add-Ins > Add-Ins > Gusset > Run, and turn on Run on Startup.)"
say ""; say "  Press Return to close this window."; read -r _
