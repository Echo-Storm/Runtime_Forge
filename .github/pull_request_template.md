## What and why

## Checklist
- [ ] `venv\Scripts\python.exe tools\run_tests.py` passes (new behaviour has a test)
- [ ] New or changed downloads go through `Trust` (publisher signature and/or SHA-256) and `tools\verify_downloads.py --only <key>` passes
- [ ] README / CHANGELOG updated if users will notice
- [ ] No installer or private data in the diff
