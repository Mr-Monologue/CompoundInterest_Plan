"""python -m src.app.api 入口"""
import uvicorn
import argparse

from . import app, init_transactions_table

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8701)
    p.add_argument("--host", type=str, default="127.0.0.1")
    args = p.parse_args()
    init_transactions_table()
    uvicorn.run(app, host=args.host, port=args.port)
