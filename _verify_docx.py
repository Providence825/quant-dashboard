# -*- coding: utf-8 -*-
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(HERE, '量化交易看板-产品介绍_new.docx')

d = Document(DST)
for i, p in enumerate(d.paragraphs):
    if i < 30:
        continue
    is_img = bool(p._p.findall('.//' + qn('w:drawing')))
    print(f'[{i}]', 'IMG' if is_img else p.text[:70])

print('---')
print('total inline images:', len(d.inline_shapes))
