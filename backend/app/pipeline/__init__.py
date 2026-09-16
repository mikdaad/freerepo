"""The 4-step hybrid compliance pipeline.

Phase 1  cad_extractor.py  Deterministic extraction   (C# / ACadSharp)
Phase 2  semantic.py       Semantic identification    (DeepSeek)
Phase 3  geometry.py       Mathematical verification  (Shapely)
Phase 4  reporting.py      Compliance reporting       (DeepSeek)
"""
