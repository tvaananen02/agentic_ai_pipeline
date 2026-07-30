from pathlib import Path
import subprocess
from config import KNOWN_ARTIFACT_DIRS, REQUIRED_PROJECT_FILES

def verify_via_filesystem(workspace: Path, project_name: str) -> tuple[bool, str]:
    canonical_dir, actions = reconcile_project_layout(workspace, project_name)

    missing = [a for a in actions if a.startswith("MISSING")]
    if missing:
        detail = "; ".join(missing)
        return False, detail

    solution = canonical_dir / "solution.py"
    test_file = canonical_dir / "test_solution.py"
    if not solution.exists():
        return False, "solution.py was never created"
    if not test_file.exists():
        return False, "test_solution.py is missing from the project directory"
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", str(test_file), "-v"],
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "pytest timed out"

    output = result.stdout + result.stderr
    passed = result.returncode == 0 and "passed" in output.lower()
    if actions:
        output = "reconciliation actions: " + "; ".join(actions) + "\n\n" + output
    return passed, output

def reconcile_project_layout(workspace: Path, project_name: str) -> tuple[Path, list[str]]:
    actions = []
    candidate_dirs = [d for d in workspace.iterdir()
                       if d.is_dir() and d.name not in KNOWN_ARTIFACT_DIRS]
    if len(candidate_dirs) == 1:
        canonical = candidate_dirs[0]
    elif len(candidate_dirs) == 0:
        canonical = workspace / project_name
        canonical.mkdir(exist_ok=True)
        actions.append(f"created missing project dir {canonical.name}")
    else:
        match = next((d for d in candidate_dirs
                       if project_name in d.name or d.name in project_name), None)
        if match:
            canonical = match
        else:
            canonical = max(candidate_dirs, key=lambda d: d.stat().st_mtime)
            actions.append(
                f"AMBIGUOUS: {len(candidate_dirs)} candidates, no name match to "
                f"'{project_name}', picked most recent ({canonical.name}) - flag for human review"
            )

    for filename in REQUIRED_PROJECT_FILES:
        target = canonical / filename
        if target.exists():
            continue
        root_copy = workspace / filename
        if root_copy.exists():
            root_copy.rename(target)
            actions.append(f"moved {filename} from workspace root")
            continue
        found = next((p for p in workspace.rglob(filename) if p != target), None)
        if found:
            found.rename(target)
            actions.append(f"moved {filename} from {found.parent.name}/")
        else:
            actions.append(f"MISSING: {filename} not found anywhere")

    return canonical, actions    