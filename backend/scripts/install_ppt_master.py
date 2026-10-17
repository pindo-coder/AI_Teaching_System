"""Install the pinned, complete upstream distribution; never install at request time.

Use --archive for an offline deployment. Source identity and every distribution
file are verified before publication. No upstream script is executed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from urllib.request import urlopen

BACKEND = Path(__file__).resolve().parents[1]
LOCK = BACKEND / "presentation_runtime/ppt-master.lock.json"
DESTINATION = BACKEND / "presentation_runtime/vendor/ppt-master"


def tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("PPT Master 分发包不能包含符号链接")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            count += 1
    return digest.hexdigest(), count


def install(archive: Path | None = None) -> Path:
    lock = json.loads(LOCK.read_text())
    if DESTINATION.exists():
        actual, count = tree_digest(DESTINATION)
        if actual == lock["tree_sha256"] and count == lock["file_count"]:
            return DESTINATION
        raise RuntimeError("已安装的 PPT Master 内容与锁文件不一致；请保留现场并重新安装到干净目录")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ppt-master-install-", dir=DESTINATION.parent) as temp:
        staging = Path(temp)
        if archive is None:
            archive = staging / "source.tgz"
            url = f"https://codeload.github.com/hugohe3/ppt-master/tar.gz/{lock['commit']}"
            with urlopen(url, timeout=90) as response, archive.open("wb") as target:
                shutil.copyfileobj(response, target, length=1024 * 1024)
        distribution = staging / "distribution"
        distribution.mkdir()
        size = 0
        with tarfile.open(archive) as source:
            if source.pax_headers.get("comment") != lock["commit"]:
                raise ValueError("源码提交号不符合 PPT Master 锁文件")
            for member in source:
                parts = PurePosixPath(member.name).parts
                if len(parts) < 4 or parts[1:3] != ("skills", "ppt-master"):
                    continue
                relative = PurePosixPath(*parts[3:])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("非法归档路径")
                path = distribution.joinpath(*relative.parts)
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    size += member.size
                    if size > 200 * 1024 * 1024:
                        raise ValueError("PPT Master 分发包超过允许大小")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    stream = source.extractfile(member)
                    if stream is None:
                        raise ValueError("归档文件不可读")
                    with stream, path.open("xb") as output:
                        shutil.copyfileobj(stream, output)
                else:
                    raise ValueError("归档包含非普通文件")
        actual, count = tree_digest(distribution)
        if actual != lock["tree_sha256"] or count != lock["file_count"]:
            raise ValueError("PPT Master 分发包完整性校验失败")
        distribution.rename(DESTINATION)
    return DESTINATION


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    arguments = parser.parse_args()
    print(install(arguments.archive))
