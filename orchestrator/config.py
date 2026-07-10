from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PIPELINE_ORDER = ["re_engineer", "tester", "se_engineer"]
DOCKER_IMAGE = "sandbox-server"
DEMO_PROJECT_DIR = PROJECT_ROOT / "demo_projects"
