from simple_term_menu import TerminalMenu
BANNER = "_AI_AGENT_PIPELINE"

def start_screen() -> bool:
    print(BANNER)
    print("Hello, what would you like to do?\n")
    menu = TerminalMenu(["Start building", "Exit"], raise_error_on_interrupt=True)
    choice = menu.show()
    return choice == 0

def get_spec() -> str:
    return input("What should we build? ").strip()

def checkpoint_screen(role: str, artifact: str) -> str:
    print(f"\n----Checkpoint: {role}----")
    print(artifact[:1000])
    print("--- (truncated) ---" if len(artifact) > 1000 else "--- end ---")    
    while True:
        menu = TerminalMenu(
            ["Approve", "Reject", "View full"],
            title=f"[{role}]",
            raise_error_on_interrupt=True,
        )
        choice = menu.show()
        if choice == 0:
            return "approve"
        if choice == 1:
            return "reject"
        if choice == 2:
            print(artifact)

def done_screen(workspace, log_path):
    print(f"\nPipeline complete. Files in {workspace}")
    print(f"Run log: {log_path}")
