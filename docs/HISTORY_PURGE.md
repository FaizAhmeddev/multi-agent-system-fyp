# History purge: exact commands (run on your laptop, PowerShell)

Removes `FYP_FINAL/database/fyp_data.db` and `FYP_FINAL/logs/orchestrator.log` from every commit.

## Recommended: one script

`scripts\win\finish-agentsmind.ps1`, run next to `agentsmind.bundle` after a gate run:

```powershell
powershell -ExecutionPolicy Bypass -File .\finish-agentsmind.ps1
```

It backs up GitHub (mirror), makes a fresh clone, adds every phase branch from the bundle, purges
both files from **all** branches at once, verifies the result and runs the secrets scan. It pushes
nothing; at the end it prints the push commands for you to run. A dry run of the same steps (with
`git filter-branch`) on a copy took the files out of all 9 commits that touched them, and the secrets
scan then reported CLEAN.

## Manual steps (main only)

I ran a dry run of this purge on a throwaway clone, using git's built-in filter-branch because filter-repo isn't available in my workspace. Result: 42 commits rewritten, and 0 commits or files still reference either path afterwards.

Steps 1 to 4 touch nothing on GitHub. **Do not run step 5 until you have checked step 4.**

```powershell
# 0. Install the tool (once)
py -3.11 -m pip install git-filter-repo==2.47.0
git filter-repo --version

# 1. Mirror backup (keep this folder until the project is finished)
cd $HOME\Desktop
git clone --mirror https://github.com/FaizAhmeddev/multi-agent-system-fyp.git agentsmind-backup-2026-10-28.git

# 2. Fresh working clone for the rewrite (filter-repo refuses non-fresh clones)
git clone https://github.com/FaizAhmeddev/multi-agent-system-fyp.git agentsmind-purge
cd agentsmind-purge

# 3. Purge both paths from all history
git filter-repo --invert-paths --path FYP_FINAL/database/fyp_data.db --path FYP_FINAL/logs/orchestrator.log

# 4. Verify (each line must print nothing or 0)
git log --all --oneline -- FYP_FINAL/database/fyp_data.db FYP_FINAL/logs/orchestrator.log
git ls-tree -r main --name-only | Select-String "fyp_data.db|orchestrator.log"
git rev-list --count main      # expect 42

# 5. ONLY AFTER YOUR OK: filter-repo removes 'origin', so re-add it and force-push main
git remote add origin https://github.com/FaizAhmeddev/multi-agent-system-fyp.git
git push --force origin main
```

After step 5:
- Every commit hash changes. Delete or re-clone any other clone, including your Desktop copy, so nobody pushes the old history back.
- GitHub can keep old commits reachable by SHA for a while. To have them removed sooner, contact GitHub Support and reference the old hashes, which are in the mirror backup.
- I will re-create `phase/0-audit` on top of the new `main`. It only adds files, so the cherry-pick is clean. In Phase 1a I'll add `FYP_FINAL/logs/` and `*.db` to `.gitignore`. `FYP_FINAL/.gitignore` already ignores `*.db`, but not `logs/`.
