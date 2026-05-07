# Obsidian setup on Windows (or any new machine)

Per revised locked decision #18 (see `state/runbooks/decision-18-revision.md`),
the project's Obsidian vault notes — session hand-offs, postmortems,
operator runbooks — are git-tracked under `state/sessions/*.md`,
`state/postmortems/*.md`, and `state/runbooks/*.md`. After `git clone`
they're already on disk; you just need to point Obsidian at them.

## One-time install (Windows)

1. **Download Obsidian** — https://obsidian.md/download (Windows installer)
2. Run the installer. Default options are fine.

## Open the project's vault

1. Launch Obsidian.
2. On the start screen → **"Open folder as vault"**.
3. Navigate to: `<your-clone-path>\polymarket-5m-bot\state`
4. Click **Select Folder**.

That's it. Obsidian indexes the markdown files under `state/sessions/`,
`state/postmortems/`, `state/runbooks/`. You'll see them in the file
explorer pane on the left.

## Recommended Obsidian settings for this project

After opening the vault, go to **Settings** (gear icon, bottom-left):

- **Editor** → **Default editing mode**: `Live Preview` (renders headings/links inline)
- **Files & Links** → **New link format**: `Relative path to file`
- **Files & Links** → **Default location for new notes**: `state/sessions/`
- **Appearance** → pick a theme you like; default `Obsidian` is fine
- **Core plugins** → enable: Daily notes, Outline, Backlinks, Tags

Optional but useful:
- **Daily notes** → set folder to `state/sessions/`, format `YYYY-MM-DD`
- **Templates** → create a session-note template at
  `state/runbooks/templates/session-note.md` matching the format used in
  `state/sessions/2026-05-07-evening.md`

## What NOT to do

- **Don't enable Obsidian Sync.** The notes are sync'd via git already.
  Running both creates merge conflicts.
- **Don't store secrets in vault notes.** They're committed to GitHub.
- **Don't add `.obsidian/` to git** — it's machine-specific config, the
  default `.gitignore` handles it (`.idea/`, `.vscode/`, etc. but
  `.obsidian/` should be added explicitly if Obsidian creates it).

## Adding `.obsidian/` to gitignore (one-time, when Obsidian first writes config)

The first time you open the vault, Obsidian creates `state/.obsidian/`
with workspace + plugin settings. That directory is machine-specific
and should NOT be committed:

```bash
echo "state/.obsidian/" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore .obsidian/ workspace config"
```

## Session-note workflow

When you finish a Claude Code session that meaningfully advanced the
project, write a hand-off note at `state/sessions/<date>.md`. Pattern:

```markdown
# Session — <topic> (<date> UTC)

## What shipped
- Concise bullet list

## What's running
- PID + process names

## Where to resume
- File / prompt / branch

## Spend
- $X.XX Anthropic API
```

The next session reads this first to pick up the thread.

## Sync between machines

`git push` from the machine where you took notes; `git pull` on the
other machine. Obsidian will pick up new files automatically (it
watches the vault folder for changes).
