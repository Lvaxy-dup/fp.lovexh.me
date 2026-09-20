"""Bound decoded input sizes before handing documents to native parsers."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
import warnings
import fitz
from PIL import Image
from . import config

def validate_docx(source):
    try:
        with ZipFile(source) as archive:
            entries=archive.infolist()
            if len(entries)>2000 or sum(e.file_size for e in entries)>40*1024*1024:
                raise ValueError('Word 解压内容过大，请拆分材料')
            if any(e.flag_bits&1 or (e.file_size>1024*1024 and e.file_size/max(e.compress_size,1)>200) for e in entries):
                raise ValueError('Word 压缩结构异常或已加密')
            if 'word/document.xml' not in archive.namelist():raise ValueError('不是有效的 DOCX 文件')
    except BadZipFile:raise ValueError('Word 文件损坏')

def validate_upload(content,suffix):
    if suffix=='.docx':validate_docx(BytesIO(content))
    elif suffix in ('.txt','.md'):
        try:text=content.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('文字文件请使用 UTF-8 编码')
        if len(text)>200000:raise ValueError('文字材料超过20万字符，请拆分上传')
    elif suffix in ('.png','.jpg','.jpeg','.webp'):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    if image.width*image.height>25_000_000:raise ValueError('图片超过2500万像素，请缩小后上传')
                    if getattr(image,'n_frames',1)>1:raise ValueError('请上传单帧图片')
                    image.verify()
        except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise ValueError('图片内容损坏或像素过大')
    elif suffix=='.pdf':
        try:
            with fitz.open(stream=content,filetype='pdf') as doc:
                if doc.needs_pass:raise ValueError('请先解除 PDF 密码保护')
                if not doc.page_count or doc.page_count>config.MAX_PAGES:raise ValueError(f'每个文件最多 {config.MAX_PAGES} 页且不能为空')
                for page in doc:
                    if page.rect.is_empty or page.rect.is_infinite:raise ValueError('PDF 页面尺寸异常')
                    for image in page.get_images():
                        if image[2]*image[3]>25_000_000:raise ValueError('PDF 内嵌图片过大，请压缩或拆分')
        except fitz.FileDataError:raise ValueError('PDF 文件内容损坏')
