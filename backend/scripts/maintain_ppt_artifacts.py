"""Preview orphaned PPT storage; quarantine/restore only during offline maintenance."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.db.models  # noqa: F401
from app.db.session import SessionLocal
from app.services.ppt_native_service import artifact_root
from app.services.ppt_retention_service import PptRetentionService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--apply', action='store_true', help='移动到可恢复隔离区，绝不永久删除')
    actions.add_argument('--restore', metavar='BATCH_ID')
    parser.add_argument('--offline', action='store_true', help='确认已停止后端且不会并发启动维护')
    args = parser.parse_args()
    with SessionLocal() as db:
        service = PptRetentionService(db, artifact_root())
        if args.restore:
            result = service.restore(args.restore, offline=args.offline)
        elif args.apply:
            result = service.quarantine(days=args.days, offline=args.offline)
        else:
            result = service.plan(days=args.days)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
