#!/bin/bash
# Run by GitHub Codespaces when this repo is set as the dotfiles repo.
# Links each personal Claude Code skill into ~/.claude/skills, so edits made in
# this checkout take effect immediately and can be committed from here.
set -euo pipefail

DOTFILES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$HOME/.claude/skills"
for skill in "$DOTFILES"/claude/skills/*/; do
  name="$(basename "$skill")"
  target="$HOME/.claude/skills/$name"
  # Replace an earlier link, but never clobber a real directory someone made by hand.
  if [ -L "$target" ] || [ ! -e "$target" ]; then
    ln -sfn "${skill%/}" "$target"
  else
    echo "dotfiles: $target exists and isn't a link; leaving it alone" >&2
  fi
done
