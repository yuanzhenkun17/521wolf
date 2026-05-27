# Agent Versions

This directory stores frozen agent strategy versions.

Each version should be created under `agent_versions/<version_name>/` and should
contain at least:

- `manifest.json` — version metadata, model config, runtime flags, and source refs.
- `skills/` — immutable skill snapshot used by this version.
- `memory/` — immutable long-memory snapshot used by this version.

Runtime code is not copied here. Runtime changes are tracked by Git commit in the
main project.

