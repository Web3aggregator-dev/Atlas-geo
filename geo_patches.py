"""Репозиторий обновлений geoip.dat / geosite.dat для приложения (GeoUpdater в packages/atlas_vpn).

  python tool/geo_patches.py fetch REPO             скачать последний релиз Loyalsoldier/v2ray-rules-dat
                                                    в REPO/versions/<tag>/ (с проверкой .sha256sum)
  python tool/geo_patches.py build REPO [--keep N]  собрать REPO/public: manifest.json, full/<tag>/*.dat,
                                                    patches/<from>-<to>.<file>.bsdiff (от каждой из N
                                                    последних версий к новейшей, по умолчанию 7)

REPO — отдельный GitHub-репозиторий: приложение читает manifest.json через raw.githubusercontent.com
(пример workflow — tool/geo-repo-workflow.yml), подойдёт и любой статический хостинг.
Клиент ищет патч по sha256 своего файла, собирает новый файл и сверяет sha256; без подходящего патча
качает полный файл. Запускать раз в сутки: fetch, затем build. Нужен пакет bsdiff4 (pip install bsdiff4).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request

import bsdiff4

FILES = ("geoip.dat", "geosite.dat")
RELEASES = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases"
LATEST_API = "https://api.github.com/repos/Loyalsoldier/v2ray-rules-dat/releases/latest"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def complete(version_dir: str) -> bool:
    return all(os.path.isfile(os.path.join(version_dir, f)) for f in FILES)


def fetch(repo: str) -> None:
    with urllib.request.urlopen(LATEST_API, timeout=60) as r:
        tag = json.load(r)["tag_name"]
    dest = os.path.join(repo, "versions", tag)
    if complete(dest):
        print("already have", tag)
        return
    os.makedirs(dest, exist_ok=True)
    for name in FILES:
        url = f"{RELEASES}/download/{tag}/{name}"
        part = os.path.join(dest, name + ".part")
        urllib.request.urlretrieve(url, part)
        with urllib.request.urlopen(url + ".sha256sum", timeout=60) as r:
            want = r.read().decode().split()[0].lower()
        got = sha256_bytes(read(part))
        if got != want:
            os.remove(part)
            sys.exit(f"{name} {tag}: sha256 mismatch ({got} != {want})")
        os.replace(part, os.path.join(dest, name))
    print("fetched", tag)


def build(repo: str, keep: int) -> None:
    versions_dir = os.path.join(repo, "versions")
    versions = sorted(v for v in os.listdir(versions_dir) if complete(os.path.join(versions_dir, v)))
    if not versions:
        sys.exit("no complete versions in " + versions_dir)
    newest, older = versions[-1], versions[-keep - 1 : -1]
    public = os.path.join(repo, "public")
    full_dir = os.path.join(public, "full", newest)
    patches_dir = os.path.join(public, "patches")
    os.makedirs(full_dir, exist_ok=True)
    os.makedirs(patches_dir, exist_ok=True)
    manifest = {"version": newest, "files": {}}
    referenced = set()
    for name in FILES:
        new = read(os.path.join(versions_dir, newest, name))
        shutil.copyfile(os.path.join(versions_dir, newest, name), os.path.join(full_dir, name))
        entry = {"sha256": sha256_bytes(new), "size": len(new), "url": f"full/{newest}/{name}", "patches": []}
        for v in older:
            old = read(os.path.join(versions_dir, v, name))
            if sha256_bytes(old) == entry["sha256"]:
                continue  # файл не менялся: клиент совпадёт по sha256 без патча
            patch_name = f"{v}-{newest}.{name}.bsdiff"
            patch_path = os.path.join(patches_dir, patch_name)
            if not os.path.isfile(patch_path):
                with open(patch_path, "wb") as f:
                    f.write(bsdiff4.diff(old, new))
            patch = read(patch_path)
            referenced.add(patch_name)
            entry["patches"].append(
                {"from": sha256_bytes(old), "url": f"patches/{patch_name}", "sha256": sha256_bytes(patch), "size": len(patch)}
            )
            print(f"{name}: {v} -> {newest} patch {len(patch) / 1024:.0f} KB")
        manifest["files"][name] = entry
    with open(os.path.join(public, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    # В public остаются только новейшие полные файлы и патчи из манифеста; в versions — keep+1 последних.
    for v in os.listdir(os.path.join(public, "full")):
        if v != newest:
            shutil.rmtree(os.path.join(public, "full", v))
    for p in os.listdir(patches_dir):
        if p not in referenced:
            os.remove(os.path.join(patches_dir, p))
    for v in versions[: -keep - 1]:
        shutil.rmtree(os.path.join(versions_dir, v))
    print("manifest", newest, "patches from", older or "none")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("fetch", "build"))
    ap.add_argument("repo")
    ap.add_argument("--keep", type=int, default=7, help="сколько предыдущих версий получают патч (build)")
    args = ap.parse_args()
    if args.command == "fetch":
        fetch(args.repo)
    else:
        build(args.repo, args.keep)


if __name__ == "__main__":
    main()
