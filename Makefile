.PHONY: test test-py test-ts build-ts conformance

test: test-py test-ts conformance

test-py:
	python -m pytest packages/python/tests

build-ts:
	cd packages/typescript && tsc -p tsconfig.json

test-ts: build-ts
	cd packages/typescript && node --test dist/test/*.test.js

conformance:
	PYTHONPATH=packages/python/src python scripts/check_conformance.py
