"""app/ — LangGraph-based agent architecture.

Provides the current runtime with a clean separation:
- graphs/  — LangGraph orchestration (no LLM calls)
- services/ — LangChain components (only chain.py calls LLM)
- lib/     — business logic (calls chain, not model)
- util/    — pure helpers (zero LLM, no runtime dependency on graphs/services)
"""
