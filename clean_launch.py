"""Clean launcher — strip ALL external site-packages before importing anything."""
import sys, os

# Aggressively strip contamination: keep ONLY project venv site-packages
venv_lib = r"F:\compound-interest-plan\.venv\Lib\site-packages"
project_root = r"F:\compound-interest-plan"
backend_dir = os.path.join(project_root, "backend")

# Rebuild sys.path from scratch
new_path = [backend_dir, project_root, venv_lib]
# Add stdlib paths (filter out hermes/3.14 contamination)
for p in sys.path:
    if "hermes" in p or "3.14" in p or "Python311" in p or "Python312" in p:
        continue
    if "site-packages" in p and venv_lib not in p:
        continue
    if p and p not in new_path:
        new_path.append(p)

sys.path = new_path
os.environ["COMPOUND_DB_PATH"] = "F:/compound-interest-plan/invest.db"
os.environ.pop("PYTHONPATH", None)
os.environ.pop("PYTHONHOME", None)
os.environ.pop("VIRTUAL_ENV", None)

# Now import and run
os.chdir(project_root)
from main import app
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=9600, log_level="info")
