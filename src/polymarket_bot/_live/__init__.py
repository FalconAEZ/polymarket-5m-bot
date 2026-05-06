"""Live runtime layer — real WS, real RPC, real CLOB.

Imports from this package are forbidden in tests by anti-vibe rule #7 and
enforced via .importlinter. Tests inject fakes through the constructor
arguments of each concrete feed/storage/health module. Phase 4 paper-mode
code lives under polymarket_bot._paper and may not import from this package.
"""
