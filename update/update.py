#!/usr/bin/env python3
"""
Update Yandex Browser packages.
Usage: ./update.py <target>
"""

import sys
import requests
import hashlib
import json
import shutil
from pathlib import Path


# Constants
DEB_DIR = Path("./deb")
DEB_LOG_PATH = DEB_DIR / "deb.log"
DEB_LOG_URL = "http://repo.yandex.ru/yandex-browser/deb/logs/deb.log"
DEB_BASE_URL = "http://repo.yandex.ru/yandex-browser/deb/pool/main/y"
JSON_DIR = Path("./json")

PACKAGES = {
    "stable": "yandex-browser-stable",
    "beta": "yandex-browser-beta",
}


def safe_download(url, dest_path):
    """
    Безопасно скачивает файл:
    1. Скачивает во временный файл
    2. Проверяет, что файл не пустой
    3. Переименовывает в целевой путь
    Возвращает True при успехе, False при ошибке
    """
    temp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    
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
            print(f"  ERROR: Empty file received")
            return False
        
        # Скачиваем во временный файл
        with open(temp_path, "wb") as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
        
        # Проверяем что скачали не пустой файл
        if temp_path.stat().st_size == 0:
            print(f"  ERROR: Downloaded file is empty")
            temp_path.unlink()
            return False
        
        # Успешно — переименовываем
        shutil.move(str(temp_path), str(dest_path))
        print(f"  OK: {dest_path.name} ({dest_path.stat().st_size} bytes)")
        return True
        
    except requests.RequestException as e:
        print(f"  ERROR: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False
    except Exception as e:
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
            if len(parts) < 10:
                continue
            action = parts[2]
            package = parts[7]
            version = parts[8]

            if action != "replace":
                continue
            if versions.get(package) is not None:
                continue
            if package == PACKAGES["beta"] or package == PACKAGES["stable"]:
                versions[package] = version
            if len(versions) == 2:
                break

    return versions


def calculate_sha256(file_path):
    """Считает SHA256 файла"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
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


def update_packages():
    """Обновляет .deb пакеты если нужно"""
    
    # Парсим deb.log
    versions = parse_deb_log()
    if not versions:
        print("  ERROR: No versions found in deb.log")
        return False
    
    print(f"  Found versions:")
    for pkg, ver in versions.items():
        print(f"    {pkg}: {ver}")
    
    success = True
    for package_name, version in versions.items():
        deb_path = get_deb_path(package_name, version)
        deb_path.parent.mkdir(exist_ok=True)
        
        # Проверяем существующий файл
        if deb_path.exists():
            file_size = deb_path.stat().st_size
            if file_size > 0:
                print(f"  OK: {package_name} {version} already exists ({file_size} bytes)")
                continue
            else:
                print(f"  WARN: {package_name} {version} exists but is empty")
                deb_path.unlink()
        
        # Скачиваем
        url = f"{DEB_BASE_URL}/{package_name}/{deb_path.name}"
        if not safe_download(url, deb_path):
            print(f"  ERROR: Failed to download {package_name} {version}")
            success = False
    
    return success


def parse_version(version_str):
    """
    Разбирает строку версии в tuple для сравнения.
    Пример: "26.6.1.1003-1" -> (26, 6, 1, 1003, 1)
    """
    parts = version_str.split('-')
    main_parts = parts[0].split('.')
    build_parts = parts[1].split('.') if len(parts) > 1 else ['0']
    
    result = []
    for p in main_parts + build_parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


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
        parts = name.split('_')
        if len(parts) >= 2:
            version_str = parts[1]
            return parse_version(version_str)
        return (0,)
    
    # Сортируем по версии (по убыванию)
    deb_files.sort(key=get_version, reverse=True)
    return deb_files[0]


def update_json():
    """Обновляет JSON файлы из локальных .deb пакетов"""
    
    JSON_DIR.mkdir(exist_ok=True)

    success = True
    for package_name in PACKAGES.values():
        deb_dir = DEB_DIR / package_name
        json_path = get_json_path(package_name)
        
        # Ищем .deb файл
        deb_path = get_latest_deb_file(deb_dir)
        version = deb_path.name.split("_")[1]
        
        # Считаем SHA256
        print(f"  Processing {deb_path.name}...")
        sha256 = calculate_sha256(deb_path)
        
        # Проверяем существующий JSON
        if json_path.exists():
            with open(json_path, "r") as f:
                old_data = json.load(f)
            if old_data.get("version") == version and old_data.get("sha256") == sha256:
                print(f"  OK: {json_path.name} is up to date")
                continue
        
        # Обновляем JSON
        data = {
            "pname": package_name,
            "version": version,
            "sha256": sha256
        }
        
        # Записываем во временный файл для безопасности
        temp_json = json_path.with_suffix(json_path.suffix + ".tmp")
        with open(temp_json, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        
        # Проверяем что записалось
        try:
            with open(temp_json, "r") as f:
                json.load(f)  # Проверяем валидность
            shutil.move(str(temp_json), str(json_path))
            print(f"  OK: {json_path.name} updated (version: {version})")
        except Exception as e:
            print(f"  ERROR: Failed to write {json_path.name}: {e}")
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
    for pkg_name in PACKAGES.values():
        deb_dir = DEB_DIR / pkg_name
        if deb_dir.exists():
            deb_files = list(deb_dir.glob("*.deb"))
            if deb_files:
                print(f"  ✅ {pkg_name}: {len(deb_files)} file(s)")
                for f in deb_files:
                    size = f.stat().st_size
                    print(f"    {f.name} ({size} bytes)")
            else:
                print(f"  ⚠️  {pkg_name}: no .deb files")
        else:
            print(f"  ❌ {pkg_name}: directory not found")
    
    # JSON files
    print("\n📝 JSON files:")
    for pkg_name in PACKAGES.values():
        json_path = get_json_path(pkg_name)
        if json_path.exists():
            with open(json_path, "r") as f:
                data = json.load(f)
            print(f"  ✅ {pkg_name}.json")
            print(f"    version: {data.get('version', 'unknown')}")
            print(f"    sha256: {data.get('sha256', 'unknown')[:16]}...")
        else:
            print(f"  ❌ {pkg_name}.json: not found")
    
    print("\n" + "=" * 60)


def usage():
    print('Usage: update.py <target>')
    print('Targets: status, all, deb-log, packages, json')
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage()

    target = sys.argv[1]

    if target == "status":
        print("\n" + "=" * 60)
        print("Yandex Browser Status")
        print("=" * 60)
        status()

    elif target == "all":
        print("=" * 60)
        print("Yandex Browser Update")
        print("=" * 60)
        print("\n=== Step 1: Update deb.log ===")
        if not update_deb_log():
            sys.exit(1)
        print("\n=== Step 2: Update .deb packages ===")
        if not update_packages():
            sys.exit(1)
        print("\n=== Step 3: Update JSON files ===")
        if not update_json():
            sys.exit(1)

    elif target == "deb-log":
        if not update_deb_log():
            sys.exit(1)
    elif target == "packages":
        if not update_packages():
            sys.exit(1)
    elif target == "json":
        if not update_json():
            sys.exit(1)
    else:
        usage()

    sys.exit(0)


if __name__ == "__main__":
    main()
