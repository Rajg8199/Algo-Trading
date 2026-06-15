"""NSE/BSE EOD F&O bhavcopy import pipeline — the *free* historical option
source (the only one that exists). Parses official daily settlement files into
option_chain/ticks with computed IV/Greeks. EOD granularity: no intraday, no
bid/ask — drives the EXP-001-EOD variant, not the intraday Experiment 001.
"""
