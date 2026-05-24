# Mobile API

The mobile app should read scan results from the deployed API instead of embedding strategy logic in the APK.

## Base URL

After Render deployment, use the service URL as the base URL.

Example:

```text
https://stock-scanner-api.onrender.com
```

## Endpoints

### `GET /health`

Health check.

Response:

```json
{
  "ok": true,
  "service": "stock_scanner_api",
  "endpoints": ["/api/latest", "/api/quote-quality"]
}
```

### `GET /api/latest`

Returns the latest scan payload written to `reports/latest.json`.

Important fields for the app:

| Field | Meaning |
|---|---|
| `schema_version` | Payload schema version |
| `created_at_kst` | Scan timestamp in KST |
| `mode` | `live` or `mock` |
| `data_quality` | Quote quality summary |
| `kr_short_stocks` | Korea short-term candidates |
| `us_long_etfs` | US long-term ETF candidates |
| `kr_retirement_etfs` | Korea retirement ETF candidates |
| `fx` | USD/KRW conversion signal |

For Korea short-term candidates, display these fields first:

| Field | Meaning |
|---|---|
| `code` | Stock code |
| `name` | Stock name |
| `current_price` | Price used by the strategy |
| `price_basis` | `realtime_quote` or `last_daily_close` |
| `price_timestamp` | Quote or daily close timestamp |
| `quote_source` | Quote source when available |
| `score` | Strategy score |
| `entry` | Entry level |
| `stop_loss` | Stop level |
| `target1` | First target |
| `target2` | Second target |
| `risk_pct` | Risk width |
| `reason` | Strategy reason |
| `failure_condition` | Exit/failure condition |

### `GET /api/quote-quality`

Returns the latest quote quality report written to `reports/quote_quality_latest.json`.

Important fields:

| Field | Meaning |
|---|---|
| `total` | Number of KR short candidates checked |
| `quote_ok` | Number of candidates with realtime quote |
| `quote_failed` | Number of candidates using fallback basis |
| `quote_ok_rate` | Quote success rate |
| `by_source` | Source breakdown |
| `failures` | Top quote failures |

## App update principle

The APK should only render this JSON. Strategy changes should be delivered by updating the server-side scan and report files.

This avoids reinstalling the APK whenever strategy logic changes.
