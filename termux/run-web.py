import os

from waitress import serve

from app import create_app


serve(
    create_app(),
    host=os.environ.get("EXPENSE_BIND_HOST", "127.0.0.1"),
    port=int(os.environ.get("EXPENSE_PORT", "8082")),
    threads=int(os.environ.get("EXPENSE_THREADS", "4")),
)
