def checkpoint(role: str, artifact: str) -> str:
    """Returns 'approve' or 'reject'. Blocks until the developer decides."""
    print(f"\n--- Checkpoint: {role} ---")
    print(artifact[:1000])
    print("--- (truncated) ---" if len(artifact) > 1000 else "--- end ---")
    while True:
        choice = input("[a]pprove / [r]eject / [v]iew full: ").strip().lower()
        match choice:
            case "a":
                return "approve"
            case "r":
                return "reject"
            case "v":
                print(artifact)
            case _:
                print("Invalid choice. Try again.")

