"""Portable attachment paths, with validated compatibility for legacy absolute paths."""
from pathlib import Path, PureWindowsPath
import re
from . import config

def material_path(rid, material, root=None):
    root=Path(root or config.RUNTIME).resolve()
    raw=str(material['path']).replace('\\','/')
    parts=raw.split('/')
    # Only migrate the old .../uploads/<record>/<material>.<ext> layout.
    if len(parts)<3 or parts[-3]!='uploads' or parts[-2]!=rid:
        raise ValueError('材料文件路径异常')
    name=parts[-1]
    if not re.fullmatch(r'[A-Za-z0-9_-]+',rid) or Path(name).stem!=material['id']:
        raise ValueError('材料文件路径异常')
    path=(root/'uploads'/rid/name).resolve()
    if path.parent!=(root/'uploads'/rid).resolve() or not path.is_relative_to(root):
        raise ValueError('材料文件路径异常')
    return path

def relative_material_path(rid,material,root=None):
    root=Path(root or config.RUNTIME).resolve()
    return material_path(rid,material,root).relative_to(root).as_posix()
