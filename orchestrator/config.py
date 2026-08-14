from pathlib import Path
import os
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")
PIPELINE_ORDER = ["re_engineer", "dev"]
DOCKER_IMAGE = "sandbox-server"
DEMO_PROJECT_DIR = PROJECT_ROOT / "demo_projects"
RUN_LOGS_DIR = PROJECT_ROOT / "results" / "run_logs"
PROMPT_DIR = PROJECT_ROOT / "prompts"
USED_MODEL = os.environ.get("USED_MODEL", "openai/gpt-oss-120b")
APP_PORT = 8000
MODEL_PROFILE = os.environ.get("MODEL_PROFILE", "groq")  # "groq" or "llamacpp"
LLAMACPP_BASE_URL = os.environ.get("LLAMACPP_BASE_URL", "http://localhost:8080/v1")
LLAMACPP_MODEL = os.environ.get("LLAMACPP_MODEL", "local-model")
ENGINE = os.environ.get("ENGINE", "mcp")  # "mcp", "claude_code", or "opencode"
KNOWN_ARTIFACT_DIRS = {".pytest_cache", "__pycache__", ".git"}
REQUIRED_PROJECT_FILES = ["solution.py", "test_solution.py"]
MAX_ITERATIONS_BY_ROLE = {
    "re_engineer": 8,
    "dev": 30,
}
CRASH_LOGS_DIR = PROJECT_ROOT / "results" / "crash_logs"