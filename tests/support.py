"""Isolated backend fixtures: never read personal settings or saved sessions."""

from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def isolated_app(sessions_dir):
    """Load the actual app with empty settings and temporary session storage.

    HTTP tests use ASGITransport without lifespan (which selects real voice
    providers); model operations must be mocked by each test. Intercept the
    import-time mkdir too, so tests never touch the user's sessions directory.
    """
    name = "_inquiry_test_app_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    original_mkdir = Path.mkdir

    def safe_mkdir(path, *args, **kwargs):
        if path == ROOT / "sessions":
            return None
        return original_mkdir(path, *args, **kwargs)

    sys.modules[name] = module
    try:
        with patch.dict(os.environ, {}, clear=True), \
                patch("dotenv.load_dotenv", return_value=False), \
                patch.object(Path, "mkdir", safe_mkdir):
            spec.loader.exec_module(module)
        module.SESSIONS_DIR = Path(sessions_dir)
        module.API_KEY = "synthetic-test-key"
        yield module
    finally:
        sys.modules.pop(name, None)
