#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用10处修改到商业计划书DOCX
基于python-docx直接操作XML
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import re

def read_rewrite_file(filepath):
    """读取重写稿markdown文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def find_paragraph_by_text(doc, search_text, partial=True):
    """查找包含指定文本的段落"""
    for idx, para in enumerate(doc.paragraphs):
        if partial and search_text in para.text:
            return idx, para
        elif not partial and para.text.strip() == search_text.strip():
            return idx, para
    return -1, None

def replace_in_runs(para, old_text, new_text):
    """在段落的runs中替换文本，保持格式"""
    full_text = para.text
    if old_text not in full_text:
        return False

    # 记录第一个run的格式
    first_run = para.runs[0] if para.runs else None

    # 清空所有runs
    for run in para.runs:
        run.text = ''

    # 在第一个run写入替换后的文本
    if first_run:
        first_run.text = full_text.replace(old_text, new_text)
    else:
        para.add_run(full_text.replace(old_text, new_text))

    return True

def delete_paragraphs_range(doc, start_idx, end_idx):
    """删除指定范围的段落"""
    for _ in range(end_idx - start_idx):
        if start_idx < len(doc.paragraphs):
            p = doc.paragraphs[start_idx]
            p._element.getparent().remove(p._element)

def insert_markdown_content(doc, insert_after_idx, markdown_text):
    """
    在指定段落后插入markdown格式内容
    返回插入的段落数量
    """
    lines = markdown_text.strip().split('\n')
    inserted_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 在insert_after_idx之后插入
        if insert_after_idx + 1 < len(doc.paragraphs):
            new_para = doc.paragraphs[insert_after_idx + 1].insert_paragraph_before('')
        else:
            new_para = doc.add_paragraph('')

        # 解析markdown格式
        if line.startswith('## '):
            # 二级标题
            new_para.add_run(line[3:]).bold = True
            new_para.style = 'Heading 2'
        elif line.startswith('**') and line.endswith('**'):
            # 粗体段落标题
            new_para.add_run(line.strip('*')).bold = True
        elif line.startswith('- '):
            # 列表项 - 不使用样式，直接用文本
            new_para.text = '• ' + line[2:]
        else:
            # 普通段落
            new_para.text = line

        inserted_count += 1
        insert_after_idx += 1

    return inserted_count

def apply_all_changes(input_path, output_path):
    """应用所有10处修改"""
    doc = Document(input_path)

    print("开始应用修改...")

    # ===== 修改#0: 副标题 =====
    idx, para = find_paragraph_by_text(doc, '慧投盾·首投小白智投系统')
    if para:
        replace_in_runs(para, '慧投盾·首投小白智投系统', '慧投盾·首投智投')
        print("✓ #0 副标题已修改")

    # ===== 修改#1: 补充3个月连亏故事 =====
    idx, para = find_paragraph_by_text(doc, '首投失败率高')
    if para and idx >= 0:
        # 在该段落后插入新段落
        story = "典型案例：2024年下半年，某用户购入科技主题基金，连续3个月净值从1.2跌至0.9（-25%），恐慌割肉。割肉后第39天，基金净值回升至1.15，用户错失反弹收益，本金永久性损失15%。这种亏损-恐慌-割肉-踏空反弹的负循环，正是首投客户流失的典型路径。"
        new_para = para.insert_paragraph_before('')
        new_para.text = story
        new_para.style = para.style
        print("✓ #1 已补充3个月连亏案例")

    # ===== 修改#2: 客群重叠改储蓄论证 =====
    # 这个修改已经在2.3节重写中包含，跳过

    # ===== 修改#3/#4/#5: 重写2.3节 =====
    section_2_3_content = read_rewrite_file(r'C:\Users\20137\_rewrite_section2_3.md')
    # 去掉markdown头部注释
    section_2_3_content = re.sub(r'^#[^#].*?\n---\n', '', section_2_3_content, flags=re.DOTALL)
    section_2_3_content = section_2_3_content.split('---')[0].strip()

    idx, para = find_paragraph_by_text(doc, '2.3 ')
    if para and idx >= 0:
        # 找到2.3节的结束位置（下一个Heading 2）
        end_idx = idx + 1
        for i in range(idx + 1, len(doc.paragraphs)):
            if doc.paragraphs[i].style.name == 'Heading 2':
                end_idx = i
                break

        # 删除旧内容
        delete_paragraphs_range(doc, idx + 1, end_idx)

        # 插入新内容
        insert_markdown_content(doc, idx, section_2_3_content)
        print("✓ #3/#4/#5 已重写2.3节")

    # ===== 修改#6/#7/#8: 重写第四节 =====
    section_4_content = read_rewrite_file(r'C:\Users\20137\_rewrite_section4.md')
    section_4_content = re.sub(r'^#[^#].*?\n---\n', '', section_4_content, flags=re.DOTALL)
    section_4_content = section_4_content.split('---')[0].strip()

    idx, para = find_paragraph_by_text(doc, '四、产品方案')
    if para and idx >= 0:
        # 找到第五节开始位置
        end_idx = len(doc.paragraphs)
        for i in range(idx + 1, len(doc.paragraphs)):
            if doc.paragraphs[i].style.name == 'Heading 1' and ('五' in doc.paragraphs[i].text or '5' in doc.paragraphs[i].text):
                end_idx = i
                break

        # 删除旧内容
        delete_paragraphs_range(doc, idx + 1, end_idx)

        # 插入新内容
        insert_markdown_content(doc, idx, section_4_content)
        print("✓ #6/#7/#8 已重写第四节")

    # ===== 修改#9: 重写4.5合规设计 =====
    section_4_5_content = read_rewrite_file(r'C:\Users\20137\_rewrite_section4_5_compliance.md')
    section_4_5_content = re.sub(r'^#[^#].*?\n---\n', '', section_4_5_content, flags=re.DOTALL)
    section_4_5_content = section_4_5_content.split('---')[0].strip()

    # 查找4.4或4.5标题
    idx, para = find_paragraph_by_text(doc, '4.5 ')
    if not para:
        idx, para = find_paragraph_by_text(doc, '4.4 合规')

    if para and idx >= 0:
        # 找到下一个同级标题或更高级标题
        end_idx = len(doc.paragraphs)
        for i in range(idx + 1, len(doc.paragraphs)):
            p_style = doc.paragraphs[i].style.name
            if p_style in ['Heading 1', 'Heading 2']:
                end_idx = i
                break

        # 删除旧内容
        delete_paragraphs_range(doc, idx + 1, end_idx)

        # 插入新内容
        insert_markdown_content(doc, idx, section_4_5_content)
        print("✓ #9 已重写4.5合规设计")

    # 保存
    doc.save(output_path)
    print(f"\n✓ 所有修改已完成！")
    print(f"输出文件: {output_path}")

if __name__ == '__main__':
    input_file = r'C:\Users\20137\Desktop\慧投盾商业计划书老师批注版.docx'
    output_file = r'C:\Users\20137\Desktop\慧投盾商业计划书_修改版.docx'

    apply_all_changes(input_file, output_file)
