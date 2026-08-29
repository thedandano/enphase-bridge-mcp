# Changelog

## [1.1.0](https://github.com/thedandano/enphase-bridge-mcp/compare/v1.0.0...v1.1.0) (2026-08-29)


### Features

* add /healthz liveness route for container healthchecks ([0859dcc](https://github.com/thedandano/enphase-bridge-mcp/commit/0859dcc7d0cd6921117fc9c49788703c643f1eda))
* add /healthz liveness route for container healthchecks ([bdabec1](https://github.com/thedandano/enphase-bridge-mcp/commit/bdabec163e30c47397283ff12f6e82c0f2d57594))
* containerize the MCP server (multi-stage uv build, non-root, healthcheck) ([91f1587](https://github.com/thedandano/enphase-bridge-mcp/commit/91f1587eb7e5b437255a3e8421926bb025f8e4d2))
* default the plugin to the homelab MCP URL; document Docker deployment ([c61794c](https://github.com/thedandano/enphase-bridge-mcp/commit/c61794ca757d6a391073e47b1480bf722bf4a899))
* publish multi-arch image to GHCR after green CI ([64af96d](https://github.com/thedandano/enphase-bridge-mcp/commit/64af96db08cc52c6f23d169e980b206b070f42c8))


### Bug Fixes

* address review findings on healthz ([4413826](https://github.com/thedandano/enphase-bridge-mcp/commit/44138266761fdccb1a4dabaf87591d664cdd42ee))
* address review findings on healthz ([b665036](https://github.com/thedandano/enphase-bridge-mcp/commit/b665036212fbe0f9bd40a959b27dc679d35551c6))
* close the latest-tag race window; bind version images to release commits ([5494a3c](https://github.com/thedandano/enphase-bridge-mcp/commit/5494a3c1cc5dc60c94481cfead013883b25b11e9))
* drop duplicate module-level /healthz left by the re-land merge ([b0d1349](https://github.com/thedandano/enphase-bridge-mcp/commit/b0d134981de44628a7b6880f4608c9ee10883857))
* guard CD publish against pwn-request via forked workflow_run ([75ebfec](https://github.com/thedandano/enphase-bridge-mcp/commit/75ebfeca4f0d3d88783d5fb3ed194f8ab6eddc2e))
* keep .mcp.json zero-config default as literal 127.0.0.1 ([563f711](https://github.com/thedandano/enphase-bridge-mcp/commit/563f7119997421907a9fc9dcd9406159abc4dc6a))
* keep local .env out of the Docker build context ([ef1f3ee](https://github.com/thedandano/enphase-bridge-mcp/commit/ef1f3eedfb8f48ff9e839a17cb17a073079fb581))
* mint version image tags from main runs; guard latest against stale runs ([4bc3985](https://github.com/thedandano/enphase-bridge-mcp/commit/4bc39858b959ff051b965683f23dac9e2cb03e8e))
* restrict CD publish to push-triggered CI runs; serialize per-SHA publishes ([9b969ea](https://github.com/thedandano/enphase-bridge-mcp/commit/9b969eafb6d304ae5ccf0f59cba745bd83e72d9c))
* serve /healthz from the actual running server, not just tests ([1cbe562](https://github.com/thedandano/enphase-bridge-mcp/commit/1cbe562614bffd18cc3925ce1dfa041c0bc20494))
* ship a literal plugin URL — Codex cannot expand env placeholders ([9b949de](https://github.com/thedandano/enphase-bridge-mcp/commit/9b949de454ea234b2647e2ed9310655803be5116))


### Documentation

* add docker homelab deployment plan ([55e47c5](https://github.com/thedandano/enphase-bridge-mcp/commit/55e47c553d0ef1ca8613cda18e86471fa09ecfb4))
* add docker homelab deployment plan ([259cc0a](https://github.com/thedandano/enphase-bridge-mcp/commit/259cc0aff9825ea45a7725f3db6308e23e78b73e))

## [1.0.0](https://github.com/thedandano/enphase-bridge-mcp/compare/v0.1.0...v1.0.0) (2026-08-28)


### Features

* cost tools — true-up estimate and TOU refresh ([#6](https://github.com/thedandano/enphase-bridge-mcp/issues/6)) ([95e3cab](https://github.com/thedandano/enphase-bridge-mcp/commit/95e3cabd646cbe5f8e580dae90def0f3aa538729))


### Bug Fixes

* regenerate uv.lock on release branches; drop release-as pin ([#14](https://github.com/thedandano/enphase-bridge-mcp/issues/14)) ([8d241c5](https://github.com/thedandano/enphase-bridge-mcp/commit/8d241c5a91bb918f5fa885db086a9b1dc0aae04c))
* tolerate empty test suite in pytest git hooks ([f409ac5](https://github.com/thedandano/enphase-bridge-mcp/commit/f409ac57c28345daf9a2db70899a7f5fe77d84fe))


### Miscellaneous Chores

* pin first release version ([301686b](https://github.com/thedandano/enphase-bridge-mcp/commit/301686b29a674b3643b8fe81e719992015c292a2))
