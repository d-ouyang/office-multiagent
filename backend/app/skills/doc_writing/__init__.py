"""doc_writing 能力包（P1 参考实现）。

目录约定：spec.yaml（声明）+ prompt.md（指令）+ run.py（可选编排）。
"""
from .run import FORMATS, run

__all__ = ["FORMATS", "run"]
