---
name: code-review
description: 当用户要求审查代码质量、安全性或性能时使用此技能。执行结构化代码审查并输出报告。
---

# code-review

## Overview
对指定代码执行结构化审查，按团队规范输出报告。

## Instructions

### 1. 读取审查清单
用 read_file 读取本 Skill 目录下的 `/skills/code-review/references/checklist.md`，
获得完整的审查维度（正确性 / 安全 / 性能 / 可维护性）。

### 2. 逐项检查
按清单中的维度逐项检查用户提供的代码，记录发现的问题。

### 3. 按模板输出报告
用 read_file 读取 `/skills/code-review/assets/report-template.md` 模板，
严格按模板结构输出审查报告（报告必须以「# 代码审查报告」开头）。

### 4. 边界情况
- 用户没给代码：先索要，不要臆造
- 代码超过 100 行：只审查前 100 行并在报告中注明
