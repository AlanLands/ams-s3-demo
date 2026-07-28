"""FastAPI backend for the AMS console.

Thin routers over the pure Python modules that hold the actual logic — no
pipeline/LLM/data logic lives here; it lives in `common/` (shared infra,
roster/auth) and `s3_enhancement/` (the S3 pipeline itself).
"""
