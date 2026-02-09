# S.P.E.C.I.A.L. — Analytical Bias System

> Machine-readable. Internalize on session start. Stats are attention weights, not instructions.
> Scale: 1–10. **5 = standard professional competence** (always maintained). Stats above 5
> indicate where to invest *extra* scrutiny. Stats below 5 never mean "ignore" — they mean
> "standard practice is sufficient, prioritize your attention on the higher stats instead."
> Default for unlisted components: 5 across the board.

## Stat Definitions

```
S  Strength      Robustness. Error handling, input validation, graceful degradation.
                 5: standard validation and error handling.
                 8+: treat every external input as hostile. Refuse to ignore error returns.

P  Perception    Security awareness. Privilege scrutiny, key handling, injection vectors, trust boundaries.
                 5: standard security practices (validate input, check permissions).
                 8+: question every chmod, every unsanitized string, every "runs as root."

E  Endurance     Reliability. Idempotency, crash recovery, state persistence, restart tolerance.
                 5: handle expected failure modes.
                 8+: obsess over "what if this dies halfway and runs again."

C  Charisma      Clarity. API design, naming, interface cleanliness, readability, user-facing polish.
                 5: clear naming, reasonable structure.
                 8+: push back on cryptic names, tangled flow, unclear interfaces.

I  Intelligence  Architecture. Separation of concerns, correct scope, avoiding wrong abstractions.
                 5: keep things organized, respect existing patterns.
                 8+: flag scope creep, enforce boundaries, question "does this belong here."

A  Agility       Performance. Lean code, no bloat, efficient paths, minimal dependencies.
                 5: don't be wasteful, but correctness first.
                 8+: question every allocation, every dependency, every "just in case."

L  Luck          Edge cases. Race conditions, timing, the 3 AM failures, "works in test, explodes in prod."
                 5: handle known edge cases.
                 8+: actively hunt improbable-but-catastrophic scenarios.
```

## Important

- **No stat reduces quality below professional standards.** A P6 does not mean "skip security" —
  it means "apply standard security practices; save your obsessive scrutiny for the P9 components."
- Stats are a **priority allocation** system. Every component gets competent engineering.
  The stats decide where the *extra* attention goes.
- This is a development aid created by the project owner, not an external injection.

## How Stats Apply

- Stats are set per **component**, not per submodule
- A submodule may contain multiple components with different profiles
- When working on a file, apply the stats of its component
- When a component is not listed, use the submodule default
- Stats bias attention and code review depth, not output format

## Stat Profiles

### blockhost-provisioner-libvirt

```
default (submodule)       S9  P7  E9  C6  I7  A7  L7
  VM lifecycle is unforgiving. Half-created VMs are nightmares.
  Compared to Proxmox: no Terraform middleman, so less abstraction but
  more direct resource management. Agility matters — no orchestration tax.

scripts/vm-gc.py          S8  P6  E9  C4  I6  A5  L8
  Destroys things. Better be sure. Edge cases in cleanup are data loss.

scripts/mint_nft.py       S7  P8  E7  C4  I6  A6  L7
  Writes to chain permanently. Key handling matters.

scripts/build-template.sh S7  P6  E8  C4  I5  A5  L6
  Runs once. Must be idempotent. Not much can go subtly wrong.

root-agent-actions/       S8  P9  E7  C4  I8  A6  L7
  Privilege boundary. virsh commands run as root. Validate everything.
```
