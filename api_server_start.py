from __future__ import annotations


def main() -> None:
    try:
        import strategies.kr_stock_lookup as lookup
        from strategies.kr_stock_lookup_enhanced import analyze_kr_stock_strategy as analyze_kr
        from strategies.kr_stock_lookup_enhanced import diagnose_scanner_exclusion, resolve_kr_stock_query
        from strategies.us_stock_lookup import analyze_us_stock_strategy, is_us_stock_query

        def analyze_any_stock_strategy(query: str) -> dict:
            if is_us_stock_query(query):
                return analyze_us_stock_strategy(query)
            return analyze_kr(query)

        lookup.analyze_kr_stock_strategy = analyze_any_stock_strategy
        lookup.resolve_kr_stock_query = resolve_kr_stock_query
        lookup.diagnose_scanner_exclusion = diagnose_scanner_exclusion
        print('[api_server_start] enhanced KR + US stock lookup enabled')
    except Exception as exc:
        print(f'[api_server_start] enhanced stock lookup skipped: {exc}')

    from api_server import main as run_api_server
    run_api_server()


if __name__ == '__main__':
    main()
