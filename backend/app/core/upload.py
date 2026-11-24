from fastapi import HTTPException, UploadFile, status


async def read_upload_limited(
    upload: UploadFile,
    *,
    max_bytes: int,
    label: str = "文件",
    chunk_size: int = 1024 * 1024,
) -> bytes:
    """分块读取上传文件并在读取过程中强校验大小上限，避免无界 read() 引发内存峰值。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            limit_mb = max(1, round(max_bytes / (1024 * 1024)))
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{label}不能超过 {limit_mb} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)
