"""Poll git status until Codex finishes, commit to current branch, then merge and push to main."""
import subprocess
import time

REPO = "D:/workspace/521wolf"
POLL_INTERVAL = 600  # 10 minutes
STABLE_COUNT = 3     # 3 consecutive checks with no changes

def run(cmd):
    result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, shell=True)
    return result.stdout.strip(), result.returncode

def current_branch():
    out, _ = run("git rev-parse --abbrev-ref HEAD")
    return out

def get_snapshot():
    raw, _ = run("git status --porcelain")
    if not raw:
        return set()
    return set(raw.splitlines())

def main():
    branch = current_branch()
    print(f"[auto-push] Watching from branch: {branch}", flush=True)
    last_snapshot = get_snapshot()
    stable = 0

    while stable < STABLE_COUNT:
        time.sleep(POLL_INTERVAL)
        current = get_snapshot()
        if current == last_snapshot:
            stable += 1
            print(f"[auto-push] No changes ({stable}/{STABLE_COUNT})", flush=True)
        else:
            stable = 0
            diff = len(current.symmetric_difference(last_snapshot))
            print(f"[auto-push] {diff} line(s) changed, resetting counter", flush=True)
            last_snapshot = current

    # Step 1: Commit on current branch
    current = get_snapshot()
    if current:
        run("git add -A")
        run('git commit -m "chore: auto-commit after Codex session [skip ci]"')
        print(f"[auto-push] Committed on {branch}", flush=True)
    else:
        print(f"[auto-push] Nothing to commit on {branch}", flush=True)

    # Step 2: Push current branch
    _, rc = run(f"git push origin {branch}")
    print(f"[auto-push] Pushed {branch} (rc={rc})", flush=True)

    # Step 3: Merge into main and push
    run("git checkout main")
    _, rc = run(f"git merge {branch} --no-edit")
    print(f"[auto-push] Merged {branch} into main (rc={rc})", flush=True)

    _, rc = run("git push origin main")
    print(f"[auto-push] Pushed main (rc={rc})", flush=True)

    # Step 4: Switch back to original branch
    run(f"git checkout {branch}")
    print(f"[auto-push] Back on {branch}. Done.", flush=True)

if __name__ == "__main__":
    main()
