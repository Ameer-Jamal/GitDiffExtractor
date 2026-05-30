# RepoLens Keyboard Shortcut Plan (Design Only)

This document defines proposed shortcuts for a future implementation pass.
No shortcuts are implemented in this milestone.

## Goals
- Speed up common actions without breaking existing text-input behavior.
- Keep shortcuts predictable across tabs.
- Avoid conflicts with common OS/Qt shortcuts.

## Proposed Shortcut Map

### Global
- `Ctrl/Cmd+1`: Focus `PR Lens` tab.
- `Ctrl/Cmd+2`: Focus `Branch Commit Viewer` tab.
- `Ctrl/Cmd+3`: Focus `Create PR` tab.
- `Ctrl/Cmd+4`: Focus `Contribution History` tab.
- `Ctrl/Cmd+5`: Focus `Settings` tab.

### PR Lens
- `Ctrl/Cmd+L`: Focus PR search input.
- `Ctrl/Cmd+Enter`: Run `List Open/Merged/All` action.
- `Ctrl/Cmd+Shift+Enter`: Run `Generate Diff`.
- `Ctrl/Cmd+J`: Move selection to next PR in list.
- `Ctrl/Cmd+K`: Move selection to previous PR in list.

### Contribution History
- `Ctrl/Cmd+L`: Focus query search input.
- `Ctrl/Cmd+Enter`: Run `Run Query`.
- `Esc`: Trigger `Cancel` when query is running.
- `Ctrl/Cmd+E`: Trigger `Export Results` when a result set exists.

### Settings
- `Ctrl/Cmd+R`: `Load Repositories`.
- `Ctrl/Cmd+Shift+R`: `Refresh` repositories.
- `Ctrl/Cmd+S`: `Use Selected Repositories`.
- `Ctrl/Cmd+F`: Focus repository search input.

## Conflict and Behavior Notes
- Do not bind shortcuts that fire while focus is inside multiline text widgets.
- Keep `Ctrl/Cmd+F` behavior tab-specific to avoid stealing browser/editor-like expectations globally.
- `Esc` should only cancel active long-running operations; otherwise no-op.
- Shortcut handlers should be disabled while relevant controls are disabled.

## Implementation Guidance for Next Pass
- Prefer `QShortcut` at tab scope for tab-specific commands.
- Gate each handler with current control enabled state.
- Surface shortcut hints in button tooltips after implementation.
- Add UI tests/manual checklist for each shortcut path and conflict case.
