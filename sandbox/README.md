# sandbox/

The directory name is a leftover and is now misleading — read this before
trusting it.

- `spring-demo/` — **not a side project.** This is S3's second target,
  "ClaimsPortal": two Spring Boot 3 services (policy-service :8081,
  claims-service :8082) with synthetic MapleSure data, targeted by CR-2026-043
  / ticket AMS-103 under target id `springdemo-claims-deductible`. It is the
  proof that the pipeline handles Java/Maven, not just Python/pytest.
  Registered in `s3_enhancement/targets.py`; reset with
  `demo/reset_s3_springdemo.sh`, run with `demo/run_s3_springdemo.sh`. Its
  checked-in source is the pre-CR baseline (snapshot in `.baseline/`), and
  `tests/test_s3_spring_target.py` covers it.

## Why it still lives under sandbox/

Because the path is load-bearing. `s3_enhancement/relevance.py`'s `_document()`
deliberately folds each file's path into the text it scores:

```python
return f"{rel_path} {content}"
```

So `sandbox/spring-demo/...` is a scoring input, not merely a location.
Renaming the directory shifts every embedding, reshuffles which files the
relevance funnel selects, and desyncs that selection from the committed
codegen replay recordings in `s3_enhancement/cache/` — which were recorded
against the current paths. Verified: the CR-2026-043 beat then fails with a
hard `LLMError` ("codegen returned unexpected file set") in replay mode,
offline, with no way to recover live.

Moving it is therefore a re-record, not a rename — it needs live codegen and
testgen runs against the new paths plus a fresh `tools/verify_s3_live.py`
pass. Don't `git mv` this directory casually.
