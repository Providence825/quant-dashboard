from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import os

def create_app():
    app = Flask(__name__, static_folder='../static', static_url_path='')
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'quant-dashboard-secret')
    app.config['JSON_AS_ASCII'] = False

    readonly = os.getenv('READONLY', 'false').lower() == 'true'
    htd_only = os.getenv('HTD_ONLY', 'false').lower() == 'true'

    from .db import init_db
    init_db()

    from .routes import api
    app.register_blueprint(api)

    # HTD-only guard: only serve /htd and its required API endpoints
    if htd_only:
        HTD_ALLOWED = {
            '/htd',
            '/api/llm/status',
            '/api/llm/explain',
            '/api/llm/analyze-assessment',
            '/api/llm/analyze_custom_answer',
            '/api/market/regime',
            '/api/sentiment/current',
            '/api/sentiment/history',
            '/api/screen/candidates',
            '/api/crossasset/overnight',
            '/api/crossasset/drilldown',
            '/api/stock/search',
            '/api/backtest/result/<int:run_id>',
        }
        @app.before_request
        def _htd_only_filter():
            path = request.path
            # Allow static assets
            if path.startswith('/static/') or path.startswith('/favicon'):
                return None
            # Allow exact matches
            if path in HTD_ALLOWED:
                return None
            # Allow /api/stock/<code>/analysis pattern
            if path.startswith('/api/stock/') and path.endswith('/analysis'):
                return None
            # Allow /api/backtest/result/<run_id> pattern
            if path.startswith('/api/backtest/result/'):
                return None
            return jsonify({'error': '此实例仅提供慧投盾服务'}), 404

    # Read-only guard: reject any state-changing request. Used by the
    # public (tunneled) instance so viewers can never trade/import/etc.
    if readonly:
        @app.before_request
        def _block_writes():
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                return jsonify({'error': '只读模式，禁止操作'}), 403

    # Pre-load stock list + warm lai_qu cache at startup
    import threading
    def _preload():
        with app.app_context():
            from .data import fetcher
            print('[INIT] Preloading stock list...')
            fetcher.get_stock_list()
            print('[INIT] Stock list ready')
            print('[INIT] Backfilling index history...')
            fetcher.backfill_index_history()
            print('[INIT] Index history ready')
            # Warm lai_qu strategy cache (may take ~15s after stock list loads)
            try:
                print('[INIT] Warming lai_qu strategy cache...')
                import time as _time
                _t0 = _time.time()
                from .trading.strategies.lai_qu import get_all_lai_qu_signals
                get_all_lai_qu_signals(use_cache=False)
                _t1 = _time.time()
                print(f'[INIT] LaiQu cache warmed in {_t1-_t0:.1f}s')
            except Exception as e:
                print(f'[INIT] LaiQu warmup skipped: {e}')

            # Warm the signals route cache so first page load is instant
            try:
                print('[INIT] Warming signals route cache...')
                import time as _time2
                _t0 = _time2.time()
                from .routes import _warm_signals_cache
                _warm_signals_cache()
                _t1 = _time2.time()
                print(f'[INIT] Signals cache warmed in {_t1-_t0:.1f}s')
            except Exception as e:
                print(f'[INIT] Signals warmup skipped: {e}')

    # Read-only (public) instance: no preload writes, no scheduler/auto-trading.
    if readonly:
        print('[INIT] READONLY mode — scheduler and preload disabled')
        return app

    threading.Thread(target=_preload, daemon=True).start()

    scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
    scheduler.start()

    from .trading.scheduler import register_jobs
    register_jobs(scheduler, app)

    return app
