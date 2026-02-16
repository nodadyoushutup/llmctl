.PHONY: docs docs-clean docs-linkcheck

PYTHON3 ?= python3
ifneq ("$(wildcard .venv/bin/python3)","")
PYTHON3 := .venv/bin/python3
endif

docs:
	$(PYTHON3) -m sphinx -b html docs/sphinx docs/sphinx/_build/html

docs-clean:
	rm -rf docs/sphinx/_build docs/sphinx/api

docs-linkcheck:
	$(PYTHON3) -m sphinx -b linkcheck docs/sphinx docs/sphinx/_build/linkcheck
