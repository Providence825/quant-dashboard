#!/usr/bin/env python3
"""Backfill K-line history to 2024-01-01 (~650 trading days)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import init_db
from server.data.importer import _do_import_kline_history

init_db()
print("Starting K-line backfill (days_back=650)...")
result = _do_import_kline_history(stock_codes=None, days_back=650)
print(result)
