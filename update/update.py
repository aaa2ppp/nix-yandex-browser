#!/usr/bin/env python3
"""
Update Yandex Browser packages.
Usage: ./update.py <target>
"""  # noqa: EXE001

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests

# Constants
TMP_DIR = Path("./tmp")
DEB_DIR = Path("./deb")
DEB_LOG_PATH = DEB_DIR / "deb.log"
DEB_LOG_URL = "https://repo.yandex.ru/yandex-browser/deb/logs/deb.log"
DEB_BASE_URL = "https://repo.yandex.ru/yandex-browser/deb/pool/main/y"
JSON_DIR = Path("./json")

PACKAGES = {
    "yandex-browser-stable",
    "yandex-browser-beta",
}


def safe_download(url: str, dest_path: Path):
    """
    Безопасно скачивает файл:
    1. Скачивает во временный файл
    2. Проверяет, что файл не пустой
    3. Переименовывает в целевой путь
    Возвращает True при успехе, False при ошибке
    """
    temp_path = (TMP_DIR / dest_path.name).with_suffix(
        dest_path.suffix + "." + str(os.getpid())
    )

    try:
        # Удаляем старый временный файл если есть
        if temp_path.exists():
            temp_path.unlink()

        print(f"  Downloading {dest_path.name}...")
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        # Проверяем Content-Length
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) == 0:
            print("  ERROR: Empty file received")
            return False

        # Скачиваем во временный файл
        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):  # noqa: FURB122
                f.write(chunk)

        # Проверяем что скачали не пустой файл
        if temp_path.stat().st_size == 0:
            print("  ERROR: Downloaded file is empty")
            temp_path.unlink()
            return False

        # Успешно — переименовываем
        shutil.move(str(temp_path), str(dest_path))
        print(f"  OK: {dest_path.name} ({dest_path.stat().st_size} bytes)")
        return True

    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False


def parse_deb_log():
    """Парсит deb.log и возвращает {package_name: version}"""
    if not DEB_LOG_PATH.exists():
        return {}

    # 2026-07-28 12:51:48 replace beta deb main amd64 yandex-browser-beta 26.6.1.1005-1 26.4.1.1113-1
    versions = {}
    with open(DEB_LOG_PATH, "r") as f:
        for line in reversed(f.readlines()):
            parts = line.strip().split()
            if len(parts) < 9:
                continue
            action = parts[2]
            if action != "add" and action != "replace":
                continue
            package = parts[7]
            if package not in PACKAGES:
                continue
            if versions.get(package) is not None:
                continue
            version = parts[8]
            versions[package] = version
            if len(versions) == len(PACKAGES):
                break

    return versions


def calculate_sha256(file_path: Path):
    hash_path = file_path.with_suffix(file_path.suffix + ".sha256")
    if hash_path.exists():
        with open(hash_path, "r") as f:
            lines = f.readlines()
        if len(lines) != 0:
            return lines[0].split()[0]

    # Иначе считаем и сохраняем
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    with open(hash_path, "w") as hf:
        hf.write(f"{sha256.hexdigest()}  {file_path.name}\n")
    return sha256.hexdigest()


def get_deb_path(package_name, version):
    """Возвращает путь к .deb файлу"""
    return DEB_DIR / package_name / f"{package_name}_{version}_amd64.deb"


def get_json_path(package_name):
    """Возвращает путь к JSON файлу"""
    return JSON_DIR / f"{package_name}.json"


def update_deb_log():
    """Обновляет deb.log если нужно"""

    DEB_DIR.mkdir(exist_ok=True)

    # Проверяем существующий файл
    if DEB_LOG_PATH.exists():
        print(f"  deb.log exists ({DEB_LOG_PATH.stat().st_size} bytes)")
    else:
        print("  deb.log not found")

    # Скачиваем новый
    if not safe_download(DEB_LOG_URL, DEB_LOG_PATH):
        print("  ERROR: Failed to download deb.log")
        return False

    print("  OK: deb.log updated")
    return True


def verify_and_rename_deb(src_path: Path, dst_path: Path) -> None:
    # ar t проверяет, что архив открывается и имеет ожидаемые компоненты
    result = subprocess.run(
        ["ar", "t", str(src_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=True,
    )
    lines = result.stdout.strip().splitlines()
    has_debian = any(l.startswith("debian-binary") for l in lines)
    has_control = any(l.startswith("control.tar") for l in lines)
    has_data = any(l.startswith("data.tar") for l in lines)
    if not (has_debian and has_control and has_data):
        raise RuntimeError(f"source is not deb package: {src_path}")

    # dpkg-deb --info проверяет структуру пакета
    subprocess.run(
        ["dpkg-deb", "--info", str(src_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    # Считаем SHA‑256 — наш локальный эталон
    hash_path = src_path.with_suffix(src_path.suffix + ".sha256")
    if hash_path.exists():
        hash_path.unlink()
    calculate_sha256(src_path)

    # Переименовываем только если всё ок
    src_path.rename(dst_path)
    hash_path.rename(dst_path.parent / hash_path.name)


def update_packages():
    """Обновляет .deb пакеты если нужно"""

    not_verifed = (TMP_DIR / "not-verifed").with_suffix("." + str(os.getpid()))
    not_verifed.mkdir(exist_ok=True)
    try:
        # Парсим deb.log
        versions = parse_deb_log()
        if not versions:
            print("  ERROR: No versions found in deb.log")
            return False

        print("  Found versions:")
        for pkg, ver in versions.items():
            print(f"    {pkg}: {ver}")

        success = True
        for package_name, version in versions.items():
            deb_path = get_deb_path(package_name, version)
            deb_path.parent.mkdir(exist_ok=True)
            deb_path_not_verifited = not_verifed / deb_path.name

            # Проверяем существующий файл
            if deb_path.exists():
                file_size = deb_path.stat().st_size
                if file_size > 0:
                    print(
                        f"  OK: {package_name} {version} already exists ({file_size} bytes)"
                    )
                    continue
                else:
                    print(f"  WARN: {package_name} {version} exists but is empty")
                    deb_path.unlink()

            # Скачиваем
            url = f"{DEB_BASE_URL}/{package_name}/{deb_path.name}"
            if not safe_download(url, deb_path_not_verifited):
                print(f"  ERROR: Failed to download {package_name} {version}")
                success = False
                continue

            # Проверяем целостность .deb
            try:
                verify_and_rename_deb(deb_path_not_verifited, deb_path)
            except Exception as e:  # noqa: BLE001
                print(f"  ERROR: {e}")
                if deb_path_not_verifited.exists():
                    deb_path_not_verifited.unlink()
                success = False
    finally:
        shutil.rmtree(not_verifed, ignore_errors=True)

    return success


def parse_version(version: str):
    """
    Разбирает строку версии в tuple для сравнения.
    Пример: "26.6.1.1003-1" -> (26, 6, 1, 1003, 1)
    """
    parts = version.split("-")
    main_parts = parts[0].split(".")
    build_parts = parts[1] if len(parts) > 1 else "0"
    main_parts.append(build_parts)
    return tuple(map(int, main_parts))


def get_latest_deb_file(deb_dir):
    """
    Возвращает путь к .deb файлу с наибольшей версией.
    Если файлов нет - возвращает None.
    """
    deb_files = list(deb_dir.glob("*.deb"))
    if not deb_files:
        return None

    # Сортируем по версии
    def get_version(path):
        # Извлекаем версию из имени файла
        # yandex-browser-stable_26.6.1.1003-1_amd64.deb
        name = path.name
        parts = name.split("_")
        return parse_version(parts[1])

    # Сортируем по версии (по убыванию)
    deb_files.sort(key=get_version, reverse=True)
    return deb_files[0]


def update_json():
    """Обновляет JSON файлы из локальных .deb пакетов"""

    JSON_DIR.mkdir(exist_ok=True)

    success = True
    for package_name in PACKAGES:
        deb_dir = DEB_DIR / package_name
        json_path = get_json_path(package_name)

        # Ищем .deb файл
        deb_path = get_latest_deb_file(deb_dir)
        if deb_path is None:
            print(f"  ERROR: No .deb file found for {package_name}")
            success = False
            continue
        version = deb_path.name.split("_")[1]

        # Считаем SHA256
        print(f"  Processing {deb_path.name}...")
        sha256 = calculate_sha256(deb_path)

        # Обновляем JSON
        data = {"pname": package_name, "version": version, "sha256": sha256}

        # Записываем во временный файл для безопасности
        temp_json = (TMP_DIR / json_path.name).with_suffix(
            json_path.suffix + "." + str(os.getpid())
        )
        try:
            with open(temp_json, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            temp_json.rename(json_path)
            print(f"  OK: {json_path.name} updated (version: {version})")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: Failed to write {json_path.name}: {e}")
            if temp_json.exists():
                temp_json.unlink()
            success = False

    return success


def status():
    """Показывает текущий статус"""

    # deb.log
    print("\n📄 deb.log:")
    if DEB_LOG_PATH.exists():
        size = DEB_LOG_PATH.stat().st_size
        print(f"  ✅ exists ({size} bytes)")
        versions = parse_deb_log()
        if versions:
            print("  Latest versions:")
            for pkg, ver in versions.items():
                print(f"    {pkg}: {ver}")
    else:
        print("  ❌ not found")

    # .deb packages
    print("\n📦 .deb packages:")
    for pkg_name in PACKAGES:
        deb_dir = DEB_DIR / pkg_name
        if deb_dir.exists():
            deb_files = list(deb_dir.glob("*.deb"))
            if deb_files:
                print(f"  ✅ {pkg_name}: {len(deb_files)} file(s)")
                for f in deb_files:
                    size = f.stat().st_size
                    print(f"    {f.name} ({size} bytes)")
            else:
                print(f"  ⚠️ {pkg_name}: no .deb files")
        else:
            print(f"  ❌ {pkg_name}: directory not found")

    # JSON files
    print("\n📝 JSON files:")
    for pkg_name in PACKAGES:
        json_path = get_json_path(pkg_name)
        if json_path.exists():
            try:
                with open(json_path, "r") as f:
                    data = json.load(f)
                print(f"  ✅ {pkg_name}.json")
                print(f"    version: {data.get('version', 'unknown')}")
                print(f"    sha256: {data.get('sha256', 'unknown')[:16]}...")
            except Exception:  # noqa: BLE001
                print(f"  ⚠️ {pkg_name}.json exists but is invalid")
        else:
            print(f"  ❌ {pkg_name}.json: not found")

    print("\n" + "=" * 60)


def usage():
    print("Usage: update.py <target>")
    print("Targets: status, all, deb-log, packages, json")


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    if not shutil.which("ar"):
        print("ERROR: command 'ar' not found.")
        sys.exit(1)

    if not shutil.which("dpkg-deb"):
        print("ERROR: command 'dpkg-deb' not found. Please install dpkg package.")
        sys.exit(1)

    target = sys.argv[1]
    global TMP_DIR
    TMP_DIR = TMP_DIR / str(os.getpid())
    TMP_DIR.mkdir(exist_ok=True)
    try:
        success = run(target)
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    sys.exit(0 if success else 1)


def run(target) -> bool:
    if target == "status":
        print("\n" + "=" * 60)
        print("Yandex Browser Status")
        print("=" * 60)
        status()
        return True

    elif target == "all":
        print("=" * 60)
        print("Yandex Browser Update")
        print("=" * 60)
        print("\n=== Step 1: Update deb.log ===")
        if not update_deb_log():
            return False
        print("\n=== Step 2: Update .deb packages ===")
        if not update_packages():
            return False
        print("\n=== Step 3: Update JSON files ===")
        return update_json()

    elif target == "deb-log":
        return update_deb_log()
    elif target == "packages":
        return update_packages()
    elif target == "json":
        return update_json()

    usage()
    return False


if __name__ == "__main__":
    main()
