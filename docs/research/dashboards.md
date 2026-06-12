# Phase 2C — Grafana Research Dashboards (specification)

Grafana-first; Next.js deferred. All panels query TimescaleDB directly via the
provisioned datasource. Three dashboards, provisioned as JSON in
`infrastructure/grafana/provisioning/dashboards/` (build task in backlog).

## 1. Data Quality Dashboard  (`dq.json`)

Audience: you, every evening, 60 seconds. Question: "is today's data usable?"

| Panel | Type | Query (sketch) |
|---|---|---|
| DQ pass rate (today) | stat, thresholds 100=green, <100=red | `SELECT count(*) FILTER (WHERE passed)::float / count(*) * 100 FROM dq_checks WHERE check_date = current_date` |
| Failed checks (today) | table | `SELECT check_name, details FROM dq_checks WHERE check_date = current_date AND NOT passed` |
| DQ heatmap (90d) | state timeline, check_name × day | `SELECT check_date, check_name, passed::int FROM dq_checks WHERE check_date > now() - interval '90 days'` |
| Chain rows/day per underlying | bars | `SELECT time_bucket('1 day', ts) d, i.underlying, count(*) FROM option_chain JOIN instruments i USING (instrument_id) GROUP BY 1,2` |
| Open data gaps | table | `SELECT * FROM data_gaps WHERE NOT resolved ORDER BY detected_at DESC` |
| Max chain snapshot gap (today) | gauge, red >180s | reuse `chain_gaps` CTE from tp_research.validation.checks |
| Validation failure rate | timeseries | Prometheus: `rate(data_validation_failures_total[1h])` |

## 2. Feature Dashboard  (`features.json`)

Audience: research review. Question: "are features fresh, covered, and sane?"

| Panel | Type | Query (sketch) |
|---|---|---|
| Feature coverage % by day | timeseries | `SELECT ts::date, count(*) FROM feature_values GROUP BY 1` vs registry size × entities (27 × 2) |
| Latest feature values | table, NIFTY/SENSEX columns | `SELECT feature_name, entity, value FROM feature_values WHERE ts = (SELECT max(ts) FROM feature_values)` |
| Any feature, full history | timeseries with `$feature` + `$entity` template variables | `SELECT ts, value FROM feature_values WHERE feature_name = '$feature' AND entity = '$entity' ORDER BY ts` |
| Feature staleness | stat, red if > 1 trading day | `SELECT max(ts) FROM feature_values` |
| Group coverage matrix | table | counts per `metadata->>'group'` per day |

## 3. Volatility Dashboard  (`vol.json`)

Audience: the VRP research loop. Question: "what is the vol state right now?"

| Panel | Type | Content |
|---|---|---|
| ATM IV vs RV (the VRP picture) | timeseries, 2 series + spread | `atm_iv_front` vs `rv_yz_20d` from feature_values; shaded spread = realized VRP |
| HAR-RV forecast vs subsequent RV | timeseries | forecast quality eyeball before formal validation |
| IV percentile / IV rank | gauges | current `iv_percentile_1y`, `iv_rank_1y` |
| Term slope | timeseries, zero line | `term_slope`; negative = inversion/stress |
| Skew panel | timeseries | `put_skew_25d`, `call_skew_25d`, `smile_curvature` |
| Vol-of-vol with regime band | timeseries, threshold line at gate level | `vov_20d` |
| India VIX + percentile | timeseries + gauge | from ticks (INDIAVIX) + `vix_percentile_1y` |
| Participant net positioning | timeseries | `fii_net_idx_fut`, `client_net_idx_fut`, `client_net_idx_puts/calls` |

Conventions: template variable `$entity` (NIFTY/SENSEX) on dashboards 2–3;
all time ranges default 90d; every panel must render correctly with sparse
data (early weeks will be sparse — that is expected, not a bug).
