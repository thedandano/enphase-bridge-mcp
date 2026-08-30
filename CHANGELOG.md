# Changelog

## [1.1.2](https://github.com/thedandano/enphase-bridge-mcp/compare/v1.1.1...v1.1.2) (2026-08-30)


### Bug Fixes

* close the v1.1.1 follow-ups (troubleshoot flag, pace comparison, schema test) ([#42](https://github.com/thedandano/enphase-bridge-mcp/issues/42)) ([9c1a25b](https://github.com/thedandano/enphase-bridge-mcp/commit/9c1a25bf7ebe19554c07f16e3b85ee773299a4d2))

## [1.1.1](https://github.com/thedandano/enphase-bridge-mcp/compare/v1.1.0...v1.1.1) (2026-08-30)


### Bug Fixes

* exclude out-of-range windows from period totals; harden report comparison wording ([6ad5dbb](https://github.com/thedandano/enphase-bridge-mcp/commit/6ad5dbb145210e9fe72a583e6cc235b802d21aa9))
* flag negative consumption even when power channels balance ([f1e9f4e](https://github.com/thedandano/enphase-bridge-mcp/commit/f1e9f4e206505b3bd58974efba7cde74d38a9039))
* flag physically impossible live power readings ([7ec881c](https://github.com/thedandano/enphase-bridge-mcp/commit/7ec881cf47565fa6544ea069bc7d5b3fd69b22ff))
* flag physically impossible live power readings ([5e90b24](https://github.com/thedandano/enphase-bridge-mcp/commit/5e90b24950b344944262cb157cf4eb38e7a166ef)), closes [#24](https://github.com/thedandano/enphase-bridge-mcp/issues/24)
* handle in-progress periods honestly (partial-day comparisons, null period stats) ([9563f6c](https://github.com/thedandano/enphase-bridge-mcp/commit/9563f6c461c45ed98cfcb40d1dfc80fe7bae1295))
* handle in-progress periods honestly in tools and skills ([e5bef97](https://github.com/thedandano/enphase-bridge-mcp/commit/e5bef97861c69d608a62a7302af69405251847a1)), closes [#23](https://github.com/thedandano/enphase-bridge-mcp/issues/23) [#28](https://github.com/thedandano/enphase-bridge-mcp/issues/28)
* **skills:** catch-all error outcome explicitly skips the diagnosis template ([1137169](https://github.com/thedandano/enphase-bridge-mcp/commit/1137169119d8865ccac0c6d77e2bdc9b54b5b2fc))
* **skills:** close troubleshoot decision-table gaps from review ([d4322fc](https://github.com/thedandano/enphase-bridge-mcp/commit/d4322fcbb8c2c9e9698236c1480ecd933a6f12bd))
* **skills:** cover refresh failure, user-fixable savings errors, failed optional comparison ([60cb457](https://github.com/thedandano/enphase-bridge-mcp/commit/60cb457a65bfc13746bba8ae0335c46b8a836d2d))
* **skills:** homeowner-safe fallback when bridge is offline or has no data ([dffe735](https://github.com/thedandano/enphase-bridge-mcp/commit/dffe735e4da4402f2dfcdeb4bcc5917c97f6fea8))
* **skills:** homeowner-safe fallback when the bridge is offline or has no data ([c0d5158](https://github.com/thedandano/enphase-bridge-mcp/commit/c0d51584f939bef04b43a05993b9ba6323ee1e72)), closes [#26](https://github.com/thedandano/enphase-bridge-mcp/issues/26)
* **skills:** name gap dates only when the breakdown identifies them ([d540034](https://github.com/thedandano/enphase-bridge-mcp/commit/d54003412dc998c8dcc7be6fdfa20007badbb938))
* **skills:** safer solar-troubleshoot diagnosis (agreeing signals, daylight rule) ([f9605f1](https://github.com/thedandano/enphase-bridge-mcp/commit/f9605f1774138f48ef9c4544069797a948aa396e))
* **skills:** savings never invents TOU hours; refresh needs explicit consent ([2aca5c8](https://github.com/thedandano/enphase-bridge-mcp/commit/2aca5c8f6cca8c9ada190e79c4b7208528b0b285)), closes [#31](https://github.com/thedandano/enphase-bridge-mcp/issues/31)
* **skills:** solar-savings TOU guardrails (no invented hours, consented refresh, provenance) ([bb70efb](https://github.com/thedandano/enphase-bridge-mcp/commit/bb70efb6daee13f79dbae9d9d0e5e1485acc1054))
* **skills:** template hardening — historical day, zero baselines, gap naming, copy ([c0fffa4](https://github.com/thedandano/enphase-bridge-mcp/commit/c0fffa4421d8fed260ef1fcf112b1c1d302f1fd1)), closes [#27](https://github.com/thedandano/enphase-bridge-mcp/issues/27) [#29](https://github.com/thedandano/enphase-bridge-mcp/issues/29) [#30](https://github.com/thedandano/enphase-bridge-mcp/issues/30) [#33](https://github.com/thedandano/enphase-bridge-mcp/issues/33)
* **skills:** template hardening across check-in, report, and savings ([f905684](https://github.com/thedandano/enphase-bridge-mcp/commit/f905684d54eb70845e165560d61af9c47f85ef82))
* **skills:** troubleshoot judges production from finished days; catch-all error outcome ([3956985](https://github.com/thedandano/enphase-bridge-mcp/commit/3956985ff2ceeaa203ccbec65c6cf51633e20bd5))
* **skills:** troubleshoot requires agreeing signals and daylight-aware diagnosis ([fd6894f](https://github.com/thedandano/enphase-bridge-mcp/commit/fd6894f3652cde602e5e2aca61e294125ad60f23)), closes [#32](https://github.com/thedandano/enphase-bridge-mcp/issues/32)
* **skills:** user-fixable report errors (92-day cap, bad dates) keep their own guidance ([5c07ce2](https://github.com/thedandano/enphase-bridge-mcp/commit/5c07ce20073f98b125caa841f86546e7e92697a8))
* tool docstrings align with consented TOU refresh ([2d1f892](https://github.com/thedandano/enphase-bridge-mcp/commit/2d1f89225e4ece38c4536cca8b45e5c30ecb365f))


### Documentation

* lead README with what it does, then install, then dependencies ([b473ac7](https://github.com/thedandano/enphase-bridge-mcp/commit/b473ac7621907c1cc56c0ad2afff5bacba1f4fc1)), closes [#25](https://github.com/thedandano/enphase-bridge-mcp/issues/25)
* reorder README for public readers ([121ba7b](https://github.com/thedandano/enphase-bridge-mcp/commit/121ba7ba30f9991b07c33a91def336fc964d1732))

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
