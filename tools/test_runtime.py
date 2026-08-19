import os
import sys
from pathlib import Path


test_root = Path(sys.executable).resolve().parent / "test_data"
test_root.mkdir(parents=True, exist_ok=True)
os.environ["REQM_TEST_MODE"] = "1"
os.environ["LOCALAPPDATA"] = str(test_root)
