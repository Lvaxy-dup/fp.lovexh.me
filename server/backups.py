"""Consistent database + attachment snapshots under the store's write lock."""
import asyncio
from contextlib import closing
from datetime import datetime,timezone
import json
import logging
from pathlib import Path
import sqlite3
import tempfile
from zipfile import ZipFile,ZIP_DEFLATED
from .storage_paths import material_path

def create_backup(store,root,destination):
    root=Path(root).resolve();destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():raise ValueError('备份文件已存在，不覆盖旧备份')
    with store.lock,tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        database=Path(temporary)/'travel.db';archive=Path(temporary)/'snapshot.zip'
        with store.connect() as source,closing(sqlite3.connect(database)) as target:
            source.backup(target)
        with closing(sqlite3.connect(database)) as db:
            records=[json.loads(row[0]) for row in db.execute('SELECT body FROM records')]
        with ZipFile(archive,'w',ZIP_DEFLATED) as output:
            output.write(database,'travel.db')
            for record in records:
                for material in record['materials']:
                    path=material_path(record['id'],material,root)
                    output.write(path,path.relative_to(root).as_posix())
        archive.replace(destination)
    return destination

async def backup_loop(store,root):
    while True:
        try:
            folder=root/'backups';destination=folder/(datetime.now(timezone.utc).strftime('%Y-%m-%d')+'.zip')
            if not destination.exists():
                worker=asyncio.create_task(asyncio.to_thread(create_backup,store,root,destination))
                try:await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
            archives=sorted(folder.glob('????-??-??.zip'),reverse=True)
            for old in archives[7:]:
                if old.resolve().parent==folder.resolve():old.unlink()
        except Exception:
            logging.exception('自动备份失败；原数据保留，请检查备份目录和原件')
        await asyncio.sleep(3600)
