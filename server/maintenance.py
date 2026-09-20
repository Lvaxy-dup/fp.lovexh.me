"""Offline backup and restore: python -m server.maintenance --help."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from zipfile import ZipFile
from . import config
from .backups import create_backup
from .runtime_lock import runtime_lock
from .store import Store
from .storage_paths import material_path

def restore_backup(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('恢复目录必须不存在，避免覆盖已有数据')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(archive) as source,tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage=Path(temporary)/'restored';stage.mkdir()
        names=source.namelist()
        if 'travel.db' not in names or len(names)!=len(set(names)):raise ValueError('备份结构无效')
        for entry in source.infolist():
            if entry.filename!='travel.db' and not re.fullmatch(r'uploads/[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\.(pdf|png|jpg|jpeg|webp|txt|md|docx)',entry.filename):
                raise ValueError('备份包含不允许的路径')
            if entry.external_attr>>16 & 0o170000==0o120000:raise ValueError('备份不能包含符号链接')
            target=stage/entry.filename;target.parent.mkdir(parents=True,exist_ok=True)
            with source.open(entry) as original,target.open('wb') as output:
                import shutil
                shutil.copyfileobj(original,output)
        with closing(sqlite3.connect(stage/'travel.db')) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库校验失败')
            db.execute('SELECT id,owner,body FROM records LIMIT 1')
            for row in db.execute('SELECT body FROM records'):
                record=json.loads(row[0])
                for material in record['materials']:
                    if not material_path(record['id'],material,stage).is_file():raise ValueError('备份缺少票据原件')
        stage.rename(destination)
    return destination

def main():
    parser=argparse.ArgumentParser(description='停服后备份；恢复到全新目录，不覆盖原数据')
    commands=parser.add_subparsers(dest='command',required=True)
    backup=commands.add_parser('backup');backup.add_argument('--output',required=True)
    restore=commands.add_parser('restore');restore.add_argument('archive');restore.add_argument('--destination',required=True)
    args=parser.parse_args()
    if args.command=='backup':
        with runtime_lock(config.RUNTIME):result=create_backup(Store(),config.RUNTIME,args.output)
    else:result=restore_backup(args.archive,args.destination)
    print(result)

if __name__=='__main__':main()
