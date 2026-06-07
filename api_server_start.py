from __future__ import annotations


def main() -> None:
    try:
        import strategies.kr_stock_lookup as lookup
        from strategies.kr_stock_lookup_enhanced import analyze_kr_stock_strategy, resolve_kr_stock_query, diagnose_scanner_exclusion
        lookup.analyze_kr_stock_strategy = analyze_kr_stock_strategy
        lookup.resolve_kr_stock_query = resolve_kr_stock_query
        lookup.diagnose_scanner_exclusion = diagnose_scanner_exclusion
        print('[api_server_start] enhanced Korean stock lookup enabled')
    except Exception as exc:
        print(f'[api_server_start] enhanced Korean stock lookup skipped: {exc}')

    from api_server import main as run_api_server
    run_api_server()


if __name__ == '__main__':
    main()
