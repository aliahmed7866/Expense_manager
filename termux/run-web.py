import os
import sys
from pathlib import Path

from waitress import serve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app


serve(
    create_app(),
    host=os.environ.get("EXPENSE_BIND_HOST", "127.0.0.1"),
    port=int(os.environ.get("EXPENSE_PORT", "8082")),
    threads=int(os.environ.get("EXPENSE_THREADS", "4")),
)
