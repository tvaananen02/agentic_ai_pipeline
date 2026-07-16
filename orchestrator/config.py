from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PIPELINE_ORDER = ["re_engineer", "tester", "se_engineer"]
DOCKER_IMAGE = "sandbox-server"
DEMO_PROJECT_DIR = PROJECT_ROOT / "demo_projects"
REQUIRED_TOOL = {
    "re_engineer": "write_file",
    "tester": "write_file",
    "se_engineer": "write_file",
}
RUN_LOGS_DIR = PROJECT_ROOT / "results" / "run_logs"
PROMPT_DIR = PROJECT_ROOT / "prompts"
