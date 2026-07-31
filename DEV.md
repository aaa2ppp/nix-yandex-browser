# Development Guide

## Project structure

```
.
├── deb/
│   ├── deb.log                          # Yandex repository log (source of truth)
│   ├── yandex-browser-stable/
│   │   └── yandex-browser-stable_<version>_amd64.deb
│   └── yandex-browser-beta/
│       └── yandex-browser-beta_<version>_amd64.deb
├── json/
│   ├── yandex-browser-stable.json       # { pname, version, sha256 }
│   └── yandex-browser-beta.json
├── update/
│   ├── update.py                        # Main update script
│   └── requirements.txt                 # Python dependencies
├── package/
│   └── default.nix                      # Nix package definition
├── flake.nix                            # Flake configuration
├── Makefile                             # Development tasks
└── DEV.md                               # This file
```

## How it works

### 1. Getting the .deb

The script `update/update.py`:

1. **Downloads `deb.log`** from Yandex repository
2. **Parses the latest versions** for stable and beta
3. **Checks local `deb/` folder** for existing `.deb` files
4. **Downloads missing `.deb` files** if not present
5. **Updates `json/*.json`** with version and SHA256 from local `.deb` files

### 2. Installation

The flake uses `debDir` parameter to decide where to get `.deb`:

- **If `debDir` is set** (`NIX_YANDEX_DEB_DIR` environment variable) → uses local `.deb`
- **If `debDir` is not set** → downloads from Yandex repository

### 3. Building

```bash
# From local .deb
NIX_YANDEX_DEB_DIR=./deb nix build .#yandex-browser-stable

# From Yandex
nix build .#yandex-browser-stable
```

## Development workflow

### Update versions

```bash
# Update everything (deb.log + packages + json)
make update-all

# Or step by step:
make update-deb-log    # download deb.log only
make update-packages   # download missing .deb files
make update-json       # update JSON from local .deb files
make update-status     # check update status
```

### Install for testing

```bash
# Install from local .deb
make install-local

# Install from Yandex
make install
```

## How to get the .deb manually

You may manually get last versions from yandex repository:

```bash
# Stable
wget -P deb/yandex-browser-stable/ \
  http://repo.yandex.ru/yandex-browser/deb/pool/main/y/yandex-browser-stable/yandex-browser-stable_XX.X.X.XXX-X_amd64.deb

# Beta
wget -P deb/yandex-browser-beta/ \
  http://repo.yandex.ru/yandex-browser/deb/pool/main/y/yandex-browser-beta/yandex-browser-beta_XX.X.X.XXX-X_amd64.deb
```

Then run `make update-json` to update JSON files.

## How to build

### Local development

```bash
# Build from local .deb
nix build .#yandex-browser-stable --override-input debDir ./deb

# Or using environment variable
NIX_YANDEX_DEB_DIR=./deb nix build .#yandex-browser-stable
```

### From Yandex repository

```bash
nix build .#yandex-browser-stable
```

## Troubleshooting

### "NIX_YANDEX_DEB_DIR not set, using Yandex"

This is normal — it means the flake will download `.deb` from Yandex.

### "Local .deb file not found"

The flake expected a `.deb` file at `deb/${pname}/${pname}_${version}_amd64.deb`. Either:
1. Download it manually
2. Run `make update-packages`
3. Or remove `NIX_YANDEX_DEB_DIR` to use Yandex

### Cleaning cache

To test installation from scratch:

```bash
# Remove from profile
nix profile remove yandex-browser-stable

# Remove old generations
nix-env --delete-generations old

# Garbage collect
nix-store --gc
```

## Notes

- Yandex does **not** keep old versions of `.deb` files
- The `deb/` folder is your archive — keep it safe
- `deb.log` is the source of truth for version tracking
- JSON files are generated from local `.deb` files, not from `deb.log` directly
