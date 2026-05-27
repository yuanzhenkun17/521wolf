# Long Memory

This directory stores the current validated mainline long-term memory.

Files such as `<role>.json` and `<role>.md` are written here only after a
candidate strategy version has been validated or explicitly promoted. Self-play
runs should write provisional memory to `runs/<run_id>/memory_candidate/`
instead of mutating this directory directly.

