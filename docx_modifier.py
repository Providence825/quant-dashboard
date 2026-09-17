#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOCX 修改脚本 - 根据批注编号定位并替换内容
处理慧投盾商业计划书的10处修改
"""

from docx import Document
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph
import re

def iter_block_items(parent):
    """
    遍历文档中的段落和表格（按顺序）
    """
    if isinstance(parent, Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise ValueError("parent must be Document or _Cell")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)

def find_comment_ranges(doc):
    """
    查找文档中所有批注的范围
    返回: {comment_id: {'start_para_idx': idx, 'text': 'xxx'}}
    """
    comments = {}
    para_list = list(doc.paragraphs)

    for idx, para in enumerate(para_list):
        # 查找批注起始标记
        for run in para.runs:
            for elem in run._element.iter():
                if elem.tag.endswith('commentRangeStart'):
                    comment_id = elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                    if comment_id:
                        comments[comment_id] = {'start_para_idx': idx, 'text': para.text}

    return comments

def replace_text_in_paragraph(para, old_text, new_text):
    """
    在段落中替换文本，保持格式
    """
    full_text = para.text
    if old_text in full_text:
        # 清空段落内容
        for run in para.runs:
            run.text = ''
        # 写入新文本到第一个run
        if para.runs:
            para.runs[0].text = full_text.replace(old_text, new_text, 1)
        else:
            para.add_run(full_text.replace(old_text, new_text, 1))
        return True
    return False

def apply_modifications(doc_path, output_path, modifications):
    """
    应用所有修改

    modifications: list of dict
        [{'type': 'subtitle', 'old': 'xxx', 'new': 'yyy'},
         {'type': 'section', 'heading': '2.3', 'new_content': 'xxx'},
         ...]
    """
    doc = Document(doc_path)

    for mod in modifications:
        if mod['type'] == 'subtitle':
            # 副标题修改 - 遍历所有段落查找
            for para in doc.paragraphs:
                if replace_text_in_paragraph(para, mod['old'], mod['new']):
                    print(f"✓ 副标题已替换: {mod['old']} → {mod['new']}")
                    break

        elif mod['type'] == 'append':
            # 追加内容 - 在指定文本后插入
            for idx, para in enumerate(doc.paragraphs):
                if mod['after'] in para.text:
                    # 在当前段落后插入新段落
                    new_para = para.insert_paragraph_before(mod['new_content'])
                    new_para.style = para.style
                    print(f"✓ 已追加内容到: {mod['after'][:50]}...")
                    break

        elif mod['type'] == 'section_replace':
            # 章节整体替换 - 找到标题，替换后续内容直到下一个同级标题
            heading_found = False
            start_idx = -1
            end_idx = -1

            for idx, para in enumerate(doc.paragraphs):
                # 查找起始标题
                if mod['heading'] in para.text and para.style.name.startswith('Heading'):
                    heading_found = True
                    start_idx = idx
                    heading_level = int(para.style.name.replace('Heading', '').strip() or '1')
                    continue

                # 找到下一个同级或更高级标题作为结束点
                if heading_found and para.style.name.startswith('Heading'):
                    current_level = int(para.style.name.replace('Heading', '').strip() or '1')
                    if current_level <= heading_level:
                        end_idx = idx
                        break

            if start_idx >= 0:
                # 删除旧内容
                if end_idx < 0:
                    end_idx = len(doc.paragraphs)

                for _ in range(end_idx - start_idx - 1):
                    if start_idx + 1 < len(doc.paragraphs):
                        p = doc.paragraphs[start_idx + 1]
                        p._element.getparent().remove(p._element)

                # 插入新内容（markdown风格转换）
                lines = mod['new_content'].split('\n')
                insert_pos = start_idx + 1

                for line in lines:
                    if line.strip():
                        if line.strip().startswith('**') and line.strip().endswith('**'):
                            # 粗体标题
                            p = doc.paragraphs[start_idx].insert_paragraph_before('')
                            p.add_run(line.strip().strip('**')).bold = True
                        elif line.strip().startswith('- '):
                            # 列表项
                            p = doc.paragraphs[start_idx].insert_paragraph_before(line.strip()[2:])
                            p.style = 'List Bullet'
                        else:
                            # 普通段落
                            doc.paragraphs[start_idx].insert_paragraph_before(line.strip())

                print(f"✓ 已替换章节: {mod['heading']}")

    doc.save(output_path)
    print(f"\n✓ 修改完成，已保存到: {output_path}")

if __name__ == '__main__':
    # 修改清单
    modifications = [
        # 批注#0: 副标题
        {
            'type': 'subtitle',
            'old': '慧投盾·首投小白智投系统',
            'new': '慧投盾·首投智投'
        },

        # 批注#1: 补充3个月连亏故事
        {
            'type': 'append',
            'after': '比如用户买入某只基金',  # 需要确认原文位置
            'new_content': '2024年下半年，基金连续3个月净值从1.2跌至0.9，用户恐慌割肉后的第39天，基金净值回到1.15，错失反弹。'
        },

        # 批注#2: 客群重叠改储蓄论证
        {
            'type': 'replace_in_section',
            'section': '2.2',  # 需要确认具体章节号
            'old': '工行客群与互联网平台有大量重叠',
            'new': '工行拥有约7.4亿个人客户，其中绝大多数长期停留在低风险储蓄和理财偏好区间。当前低利率环境正在推动部分储蓄客户向权益类产品迁移，这一迁移窗口既是机遇也是压力测试——如何在合规框架内、以可持续的成本完成从"存款搬家"到"首投留存"的转化，直接关系到工行零售财富业务未来五年的增长质量。'
        }
    ]

    input_file = r'C:\Users\20137\Desktop\慧投盾商业计划书老师批注版.docx'
    output_file = r'C:\Users\20137\Desktop\慧投盾商业计划书_修改版.docx'

    # 先读取文档结构
    doc = Document(input_file)
    print("=== 文档结构分析 ===")
    for idx, para in enumerate(doc.paragraphs[:50]):  # 先看前50段
        if para.text.strip():
            print(f"[{idx}] {para.style.name}: {para.text[:80]}")

    # apply_modifications(input_file, output_file, modifications)
