# SVNAdmin4 isolated evaluation

This branch contains evaluation tools, not a production installer. It checks the
unmodified `wolcengit/SVNAdmin4` source at
`c6973ecd36b19c313f4d9f8385c9d8e6e3ef85a2` on an ephemeral Ubuntu 26.04 runner.

- Compare its authorization evaluator with the official `svnauthz` executable.
- Exercise local-only test accounts and SVN repositories, including deny cases.
- Measure native program/UI compressed size and process RSS/PSS at idle and under
  a bounded workload (four repositories, a 16 MiB asset, four concurrent API clients).
- Export outcomes and measurements only. A successful report-collection job does
  not imply the application's permission tests passed: inspect each test result.

No production service, Gitea instance, or user repository is contacted. The source
revision and test fixtures are fixed; the npm lockfile is respected. The Go binary
is built both normally and with symbol stripping to compare delivery size.
