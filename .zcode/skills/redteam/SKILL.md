---
name: redteam
description: Launch an adversarial physics-reviewer subagent over the changes since the last gate tag. Fixes nothing.
---
Launch a read-only reviewer subagent (Agent tool, general-purpose type) on the changes since the last gate tag:

`git diff $(git describe --tags --abbrev=0)`

Give it the reviewer prompt from docs/physics-reviewer.md verbatim as its task, along with the diff output. Return its findings unedited, then list which you agree with and which you dispute, with evidence. Fix nothing until the user approves.
