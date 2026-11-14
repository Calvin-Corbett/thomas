"""The Express referee: source prepared for the elevated installer, never imported by Thomas.

This folder is a trust root. Every module here imports only the standard library and its own folder, never
imports, compiles or runs submitted code, and reaches git only through ``gitenv``. Package B1 holds the Charter
(``charter``), the tree-diff derivation (``derive``), the class D content rules (``fragment``), the scrubbed git
wrapper (``gitenv``), the no-follow file seam (``nofollow``), admission (``snapshot``) and the child-process parse
runner (``isolate``).
"""
