#!/usr/bin/env python3
# noqa: EXE001

import json
import os
import re
import subprocess

import requests

OUTPATH = os.getenv("OUTPATH") or "json"
CODECS_JSON = "https://browser-resources.s3.yandex.net/linux/codecs.json"
CODECS_SNAP_JSON = "https://browser-resources.s3.yandex.net/linux/codecs_snap.json"

STRINGS_CMD = os.getenv("STRINGS") or "strings"

BROWSERS = {
    "yandex-browser-stable": (os.getenv("STABLE"), "browser"),
    "yandex-browser-beta": (os.getenv("BETA"), "browser-beta"),
}


def get_codec_sources(url) -> dict | None:
    response = requests.get(url)
    if response.ok:
        content = response.text
        return json.loads(content)
    print(f"    Failed to fetch codec links: {url}")
    return None


def extract_chromium_version(name: str) -> str | None:
    """Извлекает полную версию Chromium из бинарника Yandex Browser."""
    nix_path, folder_name = BROWSERS[name]
    browser_cmd = f"{nix_path}/opt/yandex/{folder_name}/yandex_browser"

    result = subprocess.run([STRINGS_CMD, browser_cmd], capture_output=True, text=True)  # noqa: PLW1510
    if result.returncode != 0:
        print(f"    Failed to run strings on {browser_cmd}")
        return None

    lines = result.stdout.splitlines()
    # Ищем строку, начинающуюся с "Chrome/" и содержащую версию
    pattern = re.compile(r"Chrome/(\d+\.\d+\.\d+\.\d+)")
    for line in lines:
        m = pattern.search(line)
        if m:
            return str(m.group(1)).strip()
    return None


def get_links(full_version: str) -> list:
    """Возвращает список deb-ссылок из старого словаря (три компонента)."""
    if not full_version:
        return []
    version_no_patch = ".".join(full_version.split(".")[:3])  # "148.0.7778"
    all_codec_sources = get_codec_sources(CODECS_JSON)
    return all_codec_sources.get(version_no_patch, [])


def get_snap_info(full_version: str) -> dict | None:
    """Возвращает информацию о snap-кодеке (мажорная версия)."""
    if not full_version:
        return None
    major = full_version.split(".")[0]  # "148"
    all_codec_sources = get_codec_sources(CODECS_SNAP_JSON)
    data = all_codec_sources.get(major)
    if data is not None:
        return {"version": full_version, "url": data["url"], "path": data["path"]}
    return None


def prefetch_url(url) -> str | None:
    result = subprocess.run(["nix-prefetch-url", url], capture_output=True, text=True)  # noqa: PLW1510
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def process_links(url_list) -> dict | None:
    for url in url_list:
        sha256 = prefetch_url(url)
        if sha256 is not None:
            version = url.split("/")[-1].split("_")[1].split("-")[0]
            return {"version": version, "url": url, "sha256": sha256}
    return None


def process_snap(data) -> dict | None:
    sha256 = prefetch_url(data["url"])
    if sha256 is not None:
        return {
            "version": data["version"],
            "url": data["url"],
            "path": data["path"],
            "sha256": sha256,
        }
    return None


def main():
    print("BROWSERS:", BROWSERS)
    for browser in BROWSERS:
        print(f"Processing {browser}")

        version = extract_chromium_version(browser)
        print("    version:", version)

        links = get_links(version)
        print("    links:", links)
        json_data = process_links(links)
        if json_data is not None:
            with open(f"{OUTPATH}/{browser}-codecs.json", "w") as h:
                json.dump(json_data, h, indent=2)
                h.write("\n")
            continue

        snap = get_snap_info(version)
        print("    snap:", snap)
        if snap is not None:
            json_data = process_snap(snap)
        if json_data is not None:
            with open(f"{OUTPATH}/{browser}-codecs.json", "w") as h:
                json.dump(json_data, h, indent=2)
                h.write("\n")
            continue

        print(f"    Error fetching codecs: {browser}")


if __name__ == "__main__":
    main()
