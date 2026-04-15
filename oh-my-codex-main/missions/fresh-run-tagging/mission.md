# Mission
Guarantee fresh autoresearch launches always create distinct run-tagged branches and worktree paths instead of silently reusing prior clean lanes.

Primary target:
- autoresearch worktree planning and associated tests

Success means:
1. repeated fresh launches produce distinct run identities by default
2. tests prove prior clean lanes are not silently reused for fresh runs
3. related help/contracts remain consistent
