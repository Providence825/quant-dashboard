import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DB_PATH = os.path.join(DB_DIR, 'quant.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS index_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            sh_close REAL,
            sz_close REAL,
            cy_close REAL,
            kc_close REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK(id=1),
            cash REAL NOT NULL,
            frozen REAL NOT NULL DEFAULT 0,
            total_asset REAL NOT NULL,
            initial_capital REAL NOT NULL DEFAULT 1000000,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            shares INTEGER NOT NULL,
            avg_cost REAL NOT NULL,
            current_price REAL NOT NULL DEFAULT 0,
            highest_price REAL NOT NULL DEFAULT 0,
            buy_date TEXT NOT NULL,
            buy_price REAL NOT NULL,
            can_sell_date TEXT NOT NULL,
            strategy_type TEXT NOT NULL DEFAULT 'default',
            status TEXT NOT NULL DEFAULT 'holding'
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            filled_shares INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','partial','filled','cancelled')),
            strategy_reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            amount REAL NOT NULL,
            commission REAL NOT NULL,
            stamp_tax REAL NOT NULL DEFAULT 0,
            pnl_amount REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            trigger_reason TEXT NOT NULL,
            review_tags TEXT,
            strategy TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS daily_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_asset REAL NOT NULL,
            daily_pnl REAL NOT NULL,
            daily_return_pct REAL NOT NULL,
            win_trades INTEGER NOT NULL DEFAULT 0,
            total_trades INTEGER NOT NULL DEFAULT 0,
            review_text TEXT,
            strategy_issues TEXT,
            improvement_notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS asset_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_asset REAL NOT NULL,
            cash REAL NOT NULL,
            position_value REAL NOT NULL,
            daily_return_pct REAL NOT NULL,
            cumulative_return_pct REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS market_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT '机构一手调研（福总）',
            content TEXT NOT NULL,
            note_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS screener_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            score REAL NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            change_pct REAL NOT NULL DEFAULT 0,
            volume_ratio REAL NOT NULL DEFAULT 0,
            turnover REAL NOT NULL DEFAULT 0,
            passed_level1 INTEGER NOT NULL DEFAULT 1,
            passed_level2 INTEGER NOT NULL DEFAULT 1,
            passed_level3 INTEGER NOT NULL DEFAULT 1,
            reasons TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL UNIQUE,
            stock_name TEXT NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS stocks (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            board TEXT NOT NULL,
            sector TEXT DEFAULT '',
            last_sync TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS stock_kline_daily (
            stock_code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (stock_code, date),
            FOREIGN KEY (stock_code) REFERENCES stocks(code)
        );

        CREATE INDEX IF NOT EXISTS idx_kline_code ON stock_kline_daily(stock_code);
        CREATE INDEX IF NOT EXISTS idx_kline_date ON stock_kline_daily(date);

        CREATE TABLE IF NOT EXISTS index_kline_daily (
            index_code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (index_code, date)
        );

        CREATE INDEX IF NOT EXISTS idx_indexkline_code ON index_kline_daily(index_code);
        CREATE INDEX IF NOT EXISTS idx_indexkline_date ON index_kline_daily(date);

        CREATE TABLE IF NOT EXISTS daily_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            sentiment_score REAL NOT NULL DEFAULT 0,
            phase TEXT NOT NULL DEFAULT 'neutral',
            contrarian_action TEXT NOT NULL DEFAULT 'neutral',
            contrarian_strength REAL NOT NULL DEFAULT 0,
            position_adjustment REAL NOT NULL DEFAULT 0,
            stop_adjustment REAL NOT NULL DEFAULT 1.0,
            bullish_hits INTEGER NOT NULL DEFAULT 0,
            bearish_hits INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0,
            details_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            total_items INTEGER DEFAULT 0,
            processed_items INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            params_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            progress_pct REAL NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- 每个信号发出时的原始特征 + 事后标注的结果
        -- label=1 表示信号后 N 天内上涨超 hold_threshold，0 = 未达标，-1 = 未标注
        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            strategy TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            regime TEXT NOT NULL DEFAULT 'neutral',
            features_json TEXT NOT NULL DEFAULT '{}',
            label INTEGER NOT NULL DEFAULT -1,
            outcome_pct REAL,
            label_days INTEGER NOT NULL DEFAULT 5,
            backtest_run_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_signal_log_strategy ON signal_log(strategy);
        CREATE INDEX IF NOT EXISTS idx_signal_log_regime   ON signal_log(regime);
        CREATE INDEX IF NOT EXISTS idx_signal_log_date     ON signal_log(signal_date);

        -- 预计算的策略×regime胜率缓存，定期刷新
        CREATE TABLE IF NOT EXISTS ml_winrate_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            regime TEXT NOT NULL,
            win_rate REAL NOT NULL,
            avg_win_pct REAL NOT NULL DEFAULT 0,
            avg_loss_pct REAL NOT NULL DEFAULT 0,
            sample_count INTEGER NOT NULL DEFAULT 0,
            kelly_f REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(strategy, regime)
        );

        CREATE TABLE IF NOT EXISTS assessment_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            quiz_data TEXT NOT NULL,
            ai_profile TEXT NOT NULL,
            ai_score REAL NOT NULL,
            standard_score REAL NOT NULL,
            risk_level TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_assessment_timestamp ON assessment_profiles(timestamp);

        CREATE TABLE IF NOT EXISTS compliance_signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            risk_code TEXT NOT NULL,
            signature TEXT NOT NULL,
            signed_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_compliance_user ON compliance_signatures(user_id);
        CREATE INDEX IF NOT EXISTS idx_compliance_signed_at ON compliance_signatures(signed_at);
    ''')
    # Migrate: add strategy_type column if missing
    try:
        conn.execute("ALTER TABLE positions ADD COLUMN strategy_type TEXT NOT NULL DEFAULT 'default'")
    except:
        pass
    # Migrate: add lai_qu_phase column to daily_sentiment
    try:
        conn.execute("ALTER TABLE daily_sentiment ADD COLUMN lai_qu_phase TEXT DEFAULT ''")
    except:
        pass
    # Migrate: add strategy column to trade_log (单策略归因; 历史记录留空 '未标注')
    try:
        conn.execute("ALTER TABLE trade_log ADD COLUMN strategy TEXT DEFAULT ''")
    except:
        pass
    # Migrate: add price/change_pct/volume_ratio/turnover columns to screener_results
    for col, col_type in [('price', 'REAL NOT NULL DEFAULT 0'),
                          ('change_pct', 'REAL NOT NULL DEFAULT 0'),
                          ('volume_ratio', 'REAL NOT NULL DEFAULT 0'),
                          ('turnover', 'REAL NOT NULL DEFAULT 0')]:
        try:
            conn.execute(f"ALTER TABLE screener_results ADD COLUMN {col} {col_type}")
        except:
            pass

    # Migrate: add ann_date to stock_fundamentals
    try:
        conn.execute("ALTER TABLE stock_fundamentals ADD COLUMN ann_date TEXT")
    except:
        pass

    # ── Account 2: sector momentum (板块动量账户) ─────────────────────────
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS account2 (
            id INTEGER PRIMARY KEY CHECK(id=1),
            cash REAL NOT NULL,
            frozen REAL NOT NULL DEFAULT 0,
            total_asset REAL NOT NULL,
            initial_capital REAL NOT NULL DEFAULT 1000000,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS positions2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            shares INTEGER NOT NULL,
            avg_cost REAL NOT NULL,
            current_price REAL NOT NULL DEFAULT 0,
            highest_price REAL NOT NULL DEFAULT 0,
            buy_date TEXT NOT NULL,
            buy_price REAL NOT NULL,
            can_sell_date TEXT NOT NULL,
            sector TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'holding'
        );

        CREATE TABLE IF NOT EXISTS trade_log2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),
            price REAL NOT NULL,
            shares INTEGER NOT NULL,
            amount REAL NOT NULL,
            commission REAL NOT NULL,
            stamp_tax REAL NOT NULL DEFAULT 0,
            pnl_amount REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            sector TEXT DEFAULT '',
            trigger_reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS asset_snapshot2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            total_asset REAL NOT NULL,
            cash REAL NOT NULL,
            position_value REAL NOT NULL,
            daily_return_pct REAL NOT NULL,
            cumulative_return_pct REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
    ''')

    conn.executescript('''
        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            stock_code  TEXT NOT NULL,
            report_date TEXT NOT NULL,
            roe          REAL,
            gross_margin REAL,
            net_margin   REAL,
            revenue_yoy  REAL,
            profit_yoy   REAL,
            debt_ratio   REAL,
            current_ratio REAL,
            quick_ratio  REAL,
            roa          REAL,
            total_assets REAL,
            PRIMARY KEY (stock_code, report_date)
        );
        CREATE INDEX IF NOT EXISTS idx_fundamentals_code ON stock_fundamentals(stock_code);
        CREATE INDEX IF NOT EXISTS idx_fundamentals_date ON stock_fundamentals(report_date);
    ''')

    conn.commit()

    cur = conn.execute("SELECT id FROM account WHERE id=1")
    if cur.fetchone() is None:
        initial = float(os.getenv('INITIAL_CAPITAL', 1000000))
        conn.execute("INSERT INTO account (id, cash, frozen, total_asset, initial_capital) VALUES (1,?,0,?,?)",
                     (initial, initial, initial))
        conn.commit()

    cur2 = conn.execute("SELECT id FROM account2 WHERE id=1")
    if cur2.fetchone() is None:
        initial2 = float(os.getenv('INITIAL_CAPITAL2', 1000000))
        conn.execute("INSERT INTO account2 (id, cash, frozen, total_asset, initial_capital) VALUES (1,?,0,?,?)",
                     (initial2, initial2, initial2))
        conn.commit()
    conn.close()
