from pathlib import Path
import os
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
USED_MODEL = "llama-3.3-70b-versatile"
APP_PORT = 8000
MODEL_PROFILE = os.environ.get("MODEL_PROFILE", "groq")  # "groq" or "llamacpp"
LLAMACPP_BASE_URL = os.environ.get("LLAMACPP_BASE_URL", "http://localhost:8080/v1")
LLAMACPP_MODEL = os.environ.get("LLAMACPP_MODEL", "local-model")
ENGINE = os.environ.get("ENGINE", "mcp")  # "mcp", "claude_code", or "opencode"
