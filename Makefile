TMP_DIR = ./tmp

SRC ?= .
DST ?= 1

MERGE_EXCLUDE := ! -path '$(TMP_DIR)/*' ! -path './deb/*' ! -path './.git*'

.DEFAULT_GOAL := help

VENV_DIR := .venv
PYTHON   := $(VENV_DIR)/bin/python3
PIP      := $(VENV_DIR)/bin/pip
DEB_DIR  := ./deb

$(TMP_DIR):
	mkdir -p $(TMP_DIR)

.PHONY: help venv update-all update-deb-log update-packages update-json update-status install-local install remove

help:
	@echo "  make venv              - Create virtual environment with dependencies"
	@echo "  make update-all        - Update everything (deb.log + packages + json)"
	@echo "  make update-deb-log    - Update deb.log only"
	@echo "  make update-packages   - Update .deb packages only (depends on deb.log)"
	@echo "  make update-json       - Update JSON files from local .deb files"
	@echo "  make status            - Show current status"
	@echo "  make install-local     - Install from local directory ($(DEB_DIR))"
	@echo "  make install           - Install from Yandex repository
	@echo "  make remove            - Remove package"
	@echo ""
	@echo "⚠️  No delete deb-packages! Yandex doesn't keep old versions."

venv: $(VENV_DIR)/bin/activate

$(VENV_DIR)/bin/activate: update/requirements.txt
	@echo "Creating python virtual environment..."
	@python3 -m venv $(VENV_DIR)
	@$(PIP) install -r update/requirements.txt

update-all: venv
	@$(PYTHON) update/update.py all

update-deb-log: venv
	@$(PYTHON) update/update.py deb-log

update-packages: venv
	@$(PYTHON) update/update.py packages

update-json: venv
	@$(PYTHON) update/update.py json

update-status: venv
	@$(PYTHON) update/update.py status

install-local:
	@echo "Installing from local dir..."
	@NIX_YANDEX_DEB_DIR=$(DEB_DIR) nix profile add .#yandex-browser-stable

install:
	@echo "Installing from Yandex repository..."
	@NIX_YANDEX_DEB_DIR= nix profile add .#yandex-browser-stable	

remove:
	@nix profile remove yandex-browser-stable	

.PHONY: merge patch

merge: $(TMP_DIR)
	@find $(SRC) $(MERGE_EXCLUDE) \
		-type f -exec sh -c 'f={}; printf "\n=== $${f#./} ===\n\n"; cat $$f' ';' \
		> $(TMP_DIR)/$(DST).code

patch: $(TMP_DIR)
	@git diff --staged  > $(TMP_DIR)/$(DST).patch
