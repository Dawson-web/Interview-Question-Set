#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
面经数据解析与分类处理脚本

功能：
1. 解析牛客网导出的面经 Markdown 文件
2. 提取面经元数据（标题、公司、部门、岗位、面试轮次等）
3. 对面经内容进行去重（基于链接去重 + 内容相似度去重）
4. 按"岗位/公司"文件夹结构归档输出
5. 生成汇总索引文件

用法：
    python3 parse_interview.py <输入文件路径> [--output <输出目录>] [--position <岗位名称>]

参数：
    input_file      必需，牛客网导出的 Markdown 文件路径
    --output, -o    可选，输出目录路径，默认为 ./interview-archive
    --position, -p  可选，岗位名称，默认为 "前端"
"""

import argparse
import hashlib
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional


@dataclass
class InterviewEntry:
    """面经条目数据结构"""
    index: int
    title: str
    source_type: str
    link: str
    author: str
    content: str
    company: str = ''
    department: str = ''
    position: str = ''
    round_info: str = ''
    interview_time: str = ''
    content_hash: str = ''
    is_valid: bool = True
    tags: list = field(default_factory=list)


# 公司名称映射与别名表
COMPANY_ALIASES = {
    '腾讯': ['腾讯', 'tencent', '鹅厂', '腾子'],
    '字节跳动': ['字节', '字节跳动', 'bytedance', '头条'],
    '阿里巴巴': ['阿里', '阿里巴巴', 'alibaba', '蚂蚁', '淘宝', '天猫', '钉钉'],
    '百度': ['百度', 'baidu'],
    '美团': ['美团', 'meituan'],
    '京东': ['京东', 'jd'],
    '快手': ['快手', 'kuaishou'],
    '网易': ['网易', 'netease'],
    '小红书': ['小红书', 'xiaohongshu'],
    '拼多多': ['拼多多', 'pinduoduo', 'pdd'],
    '华为': ['华为', 'huawei'],
    '微软': ['微软', 'microsoft'],
    '帆软': ['帆软', 'fanruan'],
    '传化智联': ['传化智联', '传化'],
    '滴滴': ['滴滴', 'didi'],
    'shopee': ['shopee', '虾皮'],
}

# 腾讯部门映射
TENCENT_DEPARTMENTS = {
    'wxg': ['wxg', '微信', '微信事业群', '企业微信'],
    'ieg': ['ieg', '互动娱乐', '互娱', '腾讯游戏', '天美', '光子', '魔方', '腾讯电竞'],
    'csig': ['csig', '云与智慧产业', '腾讯云', '云智'],
    'pcg': ['pcg', '平台与内容', 'QQ', '腾讯视频', '腾讯新闻', '腾讯看点'],
    'cdg': ['cdg', '企业发展', '金融科技', '腾讯金融'],
    'teg': ['teg', '技术工程', '技术架构'],
    '腾讯音乐': ['腾讯音乐', 'tme', 'qq音乐'],
    '腾讯文档': ['腾讯文档'],
}


def parse_markdown_file(filepath: str) -> tuple[dict, list[InterviewEntry]]:
    """
    解析牛客网导出的 Markdown 文件

    Args:
        filepath: Markdown 文件路径

    Returns:
        (文件元信息, 面经条目列表)
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取文件头元信息
    meta = extract_file_meta(content)

    # 按 --- 分割条目
    sections = re.split(r'\n---\n', content)

    entries = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        entry = parse_single_entry(section)
        if entry:
            entries.append(entry)

    return meta, entries


def extract_file_meta(content: str) -> dict:
    """提取文件头部元信息"""
    meta = {}
    header_match = re.match(r'#\s+(.+?)(?:\n|$)', content)
    if header_match:
        meta['title'] = header_match.group(1).strip()

    meta_patterns = {
        'export_time': r'导出时间[：:]\s*(.+?)(?:\n|$)',
        'keyword': r'关键词[：:]\s*(.+?)(?:\n|$)',
        'pages': r'抓取页数[：:]\s*(.+?)(?:\n|$)',
        'count': r'结果数[：:]\s*(.+?)(?:\n|$)',
        'dedup': r'去重[：:]\s*(.+?)(?:\n|$)',
    }

    for key, pattern in meta_patterns.items():
        match = re.search(pattern, content)
        if match:
            meta[key] = match.group(1).strip()

    return meta


def parse_single_entry(section: str) -> Optional[InterviewEntry]:
    """解析单个面经条目"""
    # 匹配标题行: ## N. 标题内容
    title_match = re.match(r'##\s+(\d+)\.\s+(.+?)(?:\n|$)', section)
    if not title_match:
        return None

    index = int(title_match.group(1))
    title = title_match.group(2).strip()

    # 提取元数据
    source_type = ''
    link = ''
    author = ''

    source_match = re.search(r'来源类型[：:]\s*(\S+)', section)
    if source_match:
        source_type = source_match.group(1)

    link_match = re.search(r'链接[：:]\s*(https?://\S+)', section)
    if link_match:
        link = link_match.group(1)

    author_match = re.search(r'作者[：:]\s*(.+?)(?:\n|$)', section)
    if author_match:
        author = author_match.group(1).strip()

    # 提取正文内容（元数据之后的部分）
    content_lines = []
    in_content = False
    for line in section.split('\n'):
        if in_content:
            content_lines.append(line)
        elif line.startswith('- 作者'):
            in_content = True

    content = '\n'.join(content_lines).strip()

    # 计算内容哈希
    content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()

    entry = InterviewEntry(
        index=index,
        title=title,
        source_type=source_type,
        link=link,
        author=author,
        content=content,
        content_hash=content_hash,
    )

    # 智能提取公司、部门、岗位信息
    extract_company_info(entry)

    # 判断是否为有效面经（有实际面试问题内容）
    entry.is_valid = validate_entry(entry)

    # 提取标签
    entry.tags = extract_tags(section)

    return entry


# 岗位名称归一化映射
POSITION_NORMALIZATION = {
    '前端': [
        '前端', '前端开发', '前端工程师', '前端开发工程师',
        '前端实习', '前端实习生', '前端暑期实习', '前端秋招',
        '前端开发工程师（实习）', '软件开发-前端开发方向',
        'web前端', 'Web前端', '前端方向',
    ],
    '后端': [
        '后端', '后端开发', '后端工程师', '后端开发工程师',
        '服务端开发', '服务端', 'Java开发', 'Go开发',
    ],
    '全栈': ['全栈', '全栈开发', '全栈工程师'],
    '客户端': ['客户端', '客户端开发', 'iOS', 'Android', '移动端'],
}


def normalize_position(position: str) -> str:
    """将岗位名称变体归一化为标准名称"""
    if not position:
        return ''
    position_stripped = position.strip()
    for standard, variants in POSITION_NORMALIZATION.items():
        for variant in variants:
            if variant == position_stripped or variant in position_stripped:
                return standard
    return position_stripped


def extract_company_info(entry: InterviewEntry):
    """从标题和内容中智能提取公司、部门、岗位信息"""
    text = f'{entry.title} {entry.content[:500]}'
    text_lower = text.lower()

    # 识别公司
    for company, aliases in COMPANY_ALIASES.items():
        for alias in aliases:
            if alias.lower() in text_lower:
                entry.company = company
                break
        if entry.company:
            break

    # 若未识别到公司，尝试从标题提取
    if not entry.company:
        # 尝试匹配 "XX公司" 或 "XX面经" 模式
        company_match = re.search(r'([^\s/|]+?)(?:前端|后端|面经|面试|秋招|春招|实习|校招|社招)', entry.title)
        if company_match:
            candidate = company_match.group(1).strip()
            if len(candidate) >= 2 and candidate not in ['求', '秋招', '前端', '25', '26']:
                entry.company = candidate

    # 已知子部门名如果被误识别为公司名，映射回母公司
    DEPT_TO_COMPANY = {}
    for dept, aliases in TENCENT_DEPARTMENTS.items():
        for alias in aliases:
            DEPT_TO_COMPANY[alias.lower()] = ('腾讯', dept)

    if entry.company and entry.company.lower() in DEPT_TO_COMPANY:
        parent_company, dept = DEPT_TO_COMPANY[entry.company.lower()]
        entry.company = parent_company
        if not entry.department:
            entry.department = dept

    # 腾讯部门识别
    if entry.company == '腾讯':
        for dept, aliases in TENCENT_DEPARTMENTS.items():
            for alias in aliases:
                if alias.lower() in text_lower:
                    entry.department = dept
                    break
            if entry.department:
                break

    # 面试轮次识别
    round_patterns = [
        (r'一面', '一面'),
        (r'二面', '二面'),
        (r'三面', '三面'),
        (r'四面', '四面'),
        (r'五面', '五面'),
        (r'(?:hr|HR)面', 'HR面'),
        (r'电话面', '电话面'),
    ]
    rounds = []
    for pattern, label in round_patterns:
        if re.search(pattern, text):
            rounds.append(label)
    if rounds:
        entry.round_info = '、'.join(rounds)

    # 面试时间提取
    time_match = re.search(r'面试时间[：:]\s*(\S+)', text)
    if time_match:
        entry.interview_time = time_match.group(1)
    else:
        # 尝试匹配日期模式
        date_match = re.search(r'(\d{4}[./]\d{1,2}[./]\d{1,2})', text)
        if date_match:
            entry.interview_time = date_match.group(1)

    # 岗位提取
    position_match = re.search(r'面试岗位[：:]\s*(.+?)(?:\s|$)', text)
    if position_match:
        entry.position = position_match.group(1).strip()
    elif '前端' in text:
        entry.position = '前端'
    elif '后端' in text:
        entry.position = '后端'

    # 岗位名称归一化：将变体统一到标准名称
    entry.position = normalize_position(entry.position)


def validate_entry(entry: InterviewEntry) -> bool:
    """
    判断面经是否包含有效面试内容

    过滤掉以下无效条目：
    - 纯提问帖（求面经/有没有面经等）
    - 内容过短无实际面试问题
    - 只是链接转载无实质内容
    - 缺乏具体面试场景描述的纯八股罗列（如仅罗列知识点关键词无上下文）
    - 纯感想/吐槽帖无面试问题
    """
    content = entry.content.strip()

    # 内容过短
    if len(content) < 30:
        return False

    # 纯提问帖
    ask_patterns = [
        r'有没有.*面经',
        r'求.*面经',
        r'求求.*面',
        r'有面过.*的吗',
        r'难吗.*有没有',
        r'有没有友友',
        r'^rt[，,]',
        r'求指教',
        r'求助',
    ]
    for pattern in ask_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            if not has_interview_questions(content):
                return False

    # 纯链接转载（内容只是网站名称）
    if re.match(r'^.{0,20}牛客网\s*牛客网在线编程\s*牛客网题解', content):
        return False

    # 纯口号/鼓励帖（无面试问题，只有感想或吐槽）
    slogan_patterns = [
        r'^.{0,10}前端面试真的要多背背题',
        r'^.{0,10}面经\s*$',
    ]
    for pattern in slogan_patterns:
        if re.search(pattern, content):
            if not has_interview_questions(content):
                return False

    # 缺乏具体描述的纯知识点罗列过滤
    # 判断标准：内容很短 + 没有编号列表 + 没有问句 + 没有场景描述
    if len(content) < 80 and not has_interview_questions(content):
        # 检查是否只是感想或无面试内容的短文
        if not re.search(r'[？?]', content):
            return False

    return True


def has_interview_questions(content: str) -> bool:
    """判断内容是否包含面试问题"""
    patterns = [
        r'\d+[.、)）]\s*\S',  # 编号列表
        r'面试问题',
        r'手撕',
        r'算法题',
        r'八股',
        r'自我介绍',
        r'项目.*介绍',
        r'[？?]',  # 包含问号
        r'怎么[做实写]',
        r'如何实现',
        r'说[一说下]',
        r'讲[一讲下]',
        r'什么是',
        r'反问',
        r'代码题',
    ]
    match_count = sum(1 for p in patterns if re.search(p, content))
    return match_count >= 2


def extract_tags(text: str) -> list:
    """提取面经中的标签"""
    tags = re.findall(r'#([^#\s]+?)#', text)
    return list(set(tags))


def deduplicate_entries(entries: list[InterviewEntry]) -> list[InterviewEntry]:
    """
    对面经条目进行去重

    去重策略：
    1. 链接完全相同 → 去重
    2. 内容哈希完全相同 → 去重
    3. 标题和作者相同且内容相似度 > 0.8 → 去重
    """
    seen_links = set()
    seen_hashes = set()
    unique_entries = []

    for entry in entries:
        # 链接去重
        if entry.link and entry.link in seen_links:
            continue

        # 内容哈希去重
        if entry.content_hash and entry.content_hash in seen_hashes:
            continue

        # 内容相似度去重
        is_duplicate = False
        for existing in unique_entries:
            if entry.author == existing.author:
                similarity = SequenceMatcher(
                    None,
                    entry.content[:200],
                    existing.content[:200],
                ).ratio()
                if similarity > 0.8:
                    is_duplicate = True
                    break

        if is_duplicate:
            continue

        if entry.link:
            seen_links.add(entry.link)
        if entry.content_hash:
            seen_hashes.add(entry.content_hash)
        unique_entries.append(entry)

    return unique_entries


def classify_entries(
    entries: list[InterviewEntry],
    default_position: str = '前端',
) -> dict[str, dict[str, list[InterviewEntry]]]:
    """
    按 岗位/公司 结构分类面经

    Returns:
        {岗位: {公司: [面经列表]}}
    """
    classified = defaultdict(lambda: defaultdict(list))

    for entry in entries:
        if not entry.is_valid:
            continue

        position = entry.position if entry.position else default_position
        company = entry.company if entry.company else '其他'

        classified[position][company].append(entry)

    return classified


# ============================================================
# 面试内容分类提取与结构化重组
# ============================================================

# 面试问题知识领域分类规则
# 每个分类包含：emoji 标识、关键词列表（按优先级排序，靠前的分类优先匹配）
CATEGORY_RULES = [
    {
        'name': '项目经验',
        'emoji': '📋',
        'keywords': [
            '项目', '业务', '上线', '用户量', '监控', '告警', '需求',
            '难点', '挑战', '成果', '产出', '优化过', '你做了',
            '实习', '工作', 'SaaS', '平台', '系统设计', '权限',
            '封装', '复用', '组件库', '你们', '你负责', '架构设计',
            '自我介绍', '介绍一下你',
        ],
    },
    {
        'name': 'React',
        'emoji': '⚛️',
        'keywords': [
            'react', 'React', 'hooks', 'hook', 'useState', 'useEffect',
            'useCallback', 'useMemo', 'useRef', 'useContext', 'useReducer',
            'useLayoutEffect', 'redux', 'fiber', '虚拟dom', '虚拟DOM',
            'jsx', 'JSX', 'diff算法', 'react-router', 'setState',
            '合成事件', 'React事件', '组件通信', 'react生命周期',
            'React 的状态', 'React的状态',
        ],
    },
    {
        'name': 'Vue',
        'emoji': '🟢',
        'keywords': [
            'vue', 'Vue', 'vuex', 'pinia', 'v-model', 'vue-router',
            '双向绑定', '双向数据绑定', '响应式原理', 'proxy', 'Proxy',
            'defineProperty', 'computed', 'watch', 'nextTick', '$nextTick',
            'vue生命周期', 'vue2', 'vue3', 'Vue2', 'Vue3',
            '组件通信', 'keep-alive', 'setup',
        ],
    },
    {
        'name': '网络与安全',
        'emoji': '🌐',
        'keywords': [
            'http', 'HTTP', 'https', 'HTTPS', 'tcp', 'TCP', 'udp', 'UDP',
            '跨域', 'cors', 'CORS', 'cookie', 'Cookie', 'session',
            'xss', 'XSS', 'csrf', 'CSRF', 'csp', 'CSP',
            '状态码', '三次握手', '四次挥手', '缓存', '强缓存', '协商缓存',
            'dns', 'DNS', '域名', 'url', 'URL', 'OSI',
            'SSL', 'TLS', 'jwt', 'JWT', 'SSO', 'token',
            '网络', '请求', 'ajax', 'Ajax', 'fetch',
            '输入url', '输入URL', '浏览器输入',
        ],
    },
    {
        'name': '工程化',
        'emoji': '📦',
        'keywords': [
            'webpack', 'Webpack', 'vite', 'Vite', 'rollup', 'Rollup',
            'babel', 'Babel', 'eslint', 'ESLint', 'loader', 'plugin',
            '打包', '构建', '编译', '热更新', 'HMR', 'tree-shaking',
            '模块化', 'commonjs', 'CommonJS', 'ESM', 'es module',
            'npm', 'yarn', 'pnpm', 'monorepo', 'CI/CD',
            '性能优化', '懒加载', '代码分割', 'code splitting',
        ],
    },
    {
        'name': 'CSS/HTML',
        'emoji': '🎨',
        'keywords': [
            'css', 'CSS', 'html', 'HTML', 'flex', 'Flex', 'grid', 'Grid',
            'BFC', 'IFC', '盒模型', '重排', '重绘', 'reflow', 'repaint',
            '居中', '布局', '定位', 'position', 'z-index',
            '响应式', '自适应', 'rem', 'em', 'vw', 'vh',
            '伪类', '伪元素', '选择器', '优先级', '权重',
            '语义化', '标签', 'float', '浮动', '清除浮动',
            'animation', '动画', 'transition', 'transform',
        ],
    },
    {
        'name': 'JavaScript 基础',
        'emoji': '💻',
        'keywords': [
            '闭包', '原型', '原型链', 'this', 'bind', 'call', 'apply',
            '作用域', '变量提升', '暂时性死区', 'let', 'const', 'var',
            'promise', 'Promise', 'async', 'await', '事件循环',
            '宏任务', '微任务', 'EventLoop', 'event loop',
            '垃圾回收', '内存泄露', '内存泄漏', 'GC',
            '深拷贝', '浅拷贝', '防抖', '节流', '柯里化',
            'es6', 'ES6', '解构', '箭头函数', '模板字符串',
            'Symbol', 'Map', 'Set', 'WeakMap', 'Proxy', 'Reflect',
            '数据类型', '类型判断', 'typeof', 'instanceof',
            '继承', 'class', 'new', '严格模式',
        ],
    },
    {
        'name': '数据结构与算法',
        'emoji': '🗃️',
        'keywords': [
            '手撕', '算法', '排序', '链表', '二叉树', '栈', '队列',
            '递归', '动态规划', 'dp', 'DP', '哈希', '数组',
            '快排', '冒泡', '归并', '二分', '双指针',
            '力扣', 'LeetCode', 'leetcode', 'lc', 'LC',
            '编程题', '代码题', '时间复杂度', '空间复杂度',
            'DFS', 'BFS', '回溯', '贪心',
        ],
    },
    {
        'name': '小程序/跨端',
        'emoji': '📱',
        'keywords': [
            '小程序', '微信小程序', 'wx', 'setData', 'uni-app', 'uniapp',
            'react native', 'ReactNative', 'flutter', 'Flutter',
            '跨端', 'Hybrid', 'hybrid', 'H5', 'webview', 'WebView',
            'electron', 'Electron', 'Taro', 'taro',
        ],
    },
    {
        'name': '浏览器原理',
        'emoji': '🔍',
        'keywords': [
            '浏览器渲染', '渲染流程', '回流', '页面渲染',
            '进程', '线程', 'V8', 'v8', '垃圾回收机制',
            'service worker', 'Service Worker', 'web worker',
            '浏览器缓存', '浏览器存储', 'localStorage', 'sessionStorage',
            'IndexedDB', '多进程', '多线程',
        ],
    },
    {
        'name': '组件库/框架原理',
        'emoji': '🔧',
        'keywords': [
            'AntD', 'antd', 'Ant Design', 'ProTable', 'ProForm',
            'Form', 'Modal', 'Element', 'element-ui',
            '源码', '底层', '底层原理', '实现原理',
        ],
    },
    {
        'name': '软技能/HR',
        'emoji': '💬',
        'keywords': [
            '反问', '职业规划', '学习方式', '为什么', '优缺点',
            '团队', '沟通', '加班', '薪资', '期望',
            'HR', 'hr', '离职', '转行',
        ],
    },
    {
        'name': 'Git/工具',
        'emoji': '🛠️',
        'keywords': [
            'git', 'Git', 'merge', 'rebase', 'cherry-pick',
            'docker', 'Docker', 'linux', 'Linux', 'nginx', 'Nginx',
            'Node', 'node', 'npm', 'koa', 'express', 'pm2',
        ],
    },
]


def extract_questions_from_content(content: str) -> tuple[list[str], list[str]]:
    """
    从面试内容中提取独立的面试问题和叙述性文本

    核心逻辑：
    1. 先对原始文本做预处理（编号拆分、emoji换行、轮次分段）
    2. 然后逐行识别：问题 vs 叙述

    Returns:
        (questions: 问题列表, narratives: 叙述性文本列表)
    """
    # 先移除标签
    clean = re.sub(r'#[^#\s]+?#', '', content).strip()

    # ====== 预处理：将挤在一行的编号列表拆开 ======
    # 在编号前插入换行（如 "xxx 1.aaa 2.bbb" → "xxx\n1.aaa\n2.bbb"）
    clean = re.sub(r'(?<=\S)\s+(\d+[.、)）]\s*(?!\d))', r'\n\1', clean)
    # 独立行首编号也确保换行
    clean = re.sub(r'(\d+[.、)）])\s*(?!\d)', r'\n\1', clean)

    # emoji 标记前换行
    clean = re.sub(r'([📍🕐💻❓🙌⏰🕒🔹🔸▶️➡️⬇⭐])', r'\n\1', clean)

    # 面试轮次关键词前换行
    round_kw = r'一面|二面|三面|四面|五面|HR面|hr面|电话面|笔试|初面|复面|终面'
    clean = re.sub(rf'(?<=\S)\s+((?:{round_kw})[\s(（:：·])', r'\n\1', clean)

    # 按行分割
    lines = clean.split('\n')
    questions = []
    narratives = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 去掉编号前缀，提取纯问题文本
        numbered_match = re.match(r'^(\d+)[.、)）]\s*(.*)', line)
        if numbered_match:
            q_text = numbered_match.group(2).strip()
            if q_text and len(q_text) > 1:
                questions.append(q_text)
            continue

        # 复选框行
        if re.match(r'^\[[ Xx]\]', line):
            q = re.sub(r'^\[[ Xx]\]\s*', '', line).strip()
            if q:
                questions.append(q)
            continue

        # 加粗的面试轮次标题 → 叙述
        if re.match(r'^\*?\*?(?:一面|二面|三面|四面|五面|HR面|笔试|初面|复面|终面)', line):
            # 如果轮次标题后还跟着实质内容，将内容部分作为叙述
            narratives.append(line)
            continue

        # 含问号的行
        if re.search(r'[？?]', line):
            if len(line) < 200:
                questions.append(line)
            else:
                # 长段落按问号边界拆分
                sub_questions = _split_by_question_boundaries(line)
                if len(sub_questions) > 1:
                    questions.extend(sub_questions)
                else:
                    narratives.append(line)
            continue

        # 短行技术关键词列表（如 "闭包 原型链 this指向 作用域"）
        if len(line) < 100 and _looks_like_question_list(line):
            # 尝试按分隔符拆分
            items = re.split(r'[/、，,]\s*|\s{2,}', line)
            if len(items) > 2:
                questions.extend([item.strip() for item in items if item.strip() and len(item.strip()) > 1])
            else:
                questions.append(line)
            continue

        # 其余内容作为叙述
        narratives.append(line)

    return questions, narratives


def _looks_like_question_list(line: str) -> bool:
    """判断一行是否看起来像是技术问题关键词列表"""
    # 检查是否包含技术关键词
    tech_keywords = [
        '闭包', '原型', 'this', '跨域', '缓存', 'http', 'css', 'flex',
        '盒模型', '布局', '排序', '算法', '手撕', '组件', 'hooks',
        'promise', 'async', '事件', 'DOM', 'diff', '生命周期',
        '作用域', '继承', '模块', 'webpack', '性能', '优化',
        '重排', '重绘', 'BFC', '浮动', '定位',
    ]
    matches = sum(1 for kw in tech_keywords if kw.lower() in line.lower())
    return matches >= 2


def classify_question(question: str) -> str:
    """
    将单个问题按关键词匹配到最佳知识领域分类

    Returns:
        分类名称，无法匹配时返回 '其他'
    """
    text_lower = question.lower()
    best_match = None
    best_score = 0

    for rule in CATEGORY_RULES:
        score = 0
        for keyword in rule['keywords']:
            if keyword.lower() in text_lower:
                score += 1
        if score > best_score:
            best_score = score
            best_match = rule['name']

    return best_match if best_match and best_score > 0 else '其他'


def classify_and_restructure_content(content: str, tags: list[str] = None) -> str:
    """
    将面试内容提取问题并按知识领域分类，生成结构化 Markdown

    Args:
        content: 原始面试内容文本
        tags: 面经标签列表

    Returns:
        结构化的 Markdown 文本
    """
    if not content or len(content.strip()) < 20:
        return format_content(content)

    # 提取标签
    all_tags = re.findall(r'#[^#\s]+?#', content)
    clean_content = re.sub(r'\s*#[^#\s]+?#', '', content).strip()

    # 提取问题和叙述
    questions, narratives = extract_questions_from_content(clean_content)

    # 如果提取到的问题太少（< 3），说明内容不适合结构化，走原有格式化
    if len(questions) < 3:
        return format_content(content)

    # 对问题进行分类
    categorized = defaultdict(list)
    for q in questions:
        category = classify_question(q)
        categorized[category].append(q)

    # 生成结构化 Markdown
    output_lines = []

    # 叙述性内容（面试概要）放在最前面
    filtered_narratives = []
    for n in narratives:
        n_stripped = n.strip()
        # 过滤掉仅为标题重复的叙述
        if n_stripped and len(n_stripped) > 5:
            filtered_narratives.append(n_stripped)

    if filtered_narratives:
        for n in filtered_narratives:
            output_lines.append(f'> {n}')
        output_lines.append('')

    # 按 CATEGORY_RULES 顺序输出分类（保持固定顺序，空分类跳过）
    category_order = [rule['name'] for rule in CATEGORY_RULES]
    # 追加 "其他" 分类
    category_order.append('其他')

    emoji_map = {rule['name']: rule['emoji'] for rule in CATEGORY_RULES}
    emoji_map['其他'] = '📝'

    for cat_name in category_order:
        if cat_name not in categorized:
            continue
        items = categorized[cat_name]
        if not items:
            continue

        emoji = emoji_map.get(cat_name, '📝')
        output_lines.append(f'#### {emoji} {cat_name}')
        for item in items:
            # 清理问题文本（去掉开头多余的空格和标点）
            item = re.sub(r'^[\s\-·•]+', '', item).strip()
            if item:
                output_lines.append(f'- {item}')
        output_lines.append('')

    # 附加标签
    if all_tags:
        unique_tags = list(dict.fromkeys(all_tags))
        output_lines.append(' '.join(unique_tags))

    result = '\n'.join(output_lines).strip()
    return result


def format_content(content: str) -> str:
    """
    格式化面经正文内容，使其更便于阅读

    处理逻辑：
    1. 提取并隔离标签到末尾
    2. 将同一行内的编号列表拆分为多行
    3. 将无编号但包含问句的长段落按句子拆分
    4. 识别 emoji 分段标记并换行
    5. 识别面试轮次分段并换行加粗
    6. 保留已有的多行格式不做破坏
    """
    if not content:
        return content

    # 步骤0：全局提取标签，统一放到末尾
    all_tags = re.findall(r'#[^#\s]+?#', content)
    content = re.sub(r'\s*#[^#\s]+?#', '', content).strip()

    # 按已有换行符分割，逐行处理
    raw_lines = content.split('\n')
    result_lines = []

    for line in raw_lines:
        line = line.strip()
        if not line:
            result_lines.append('')
            continue

        # 已经是单独的编号行（短行），直接保留
        if _is_single_numbered_line(line):
            result_lines.append(line)
            continue

        # 已经是复选框行，直接保留
        if re.match(r'^\[[ Xx]\]', line):
            result_lines.append(line)
            continue

        # 对长行进行格式化处理
        formatted = _format_long_line(line)
        result_lines.append(formatted)

    # 合并结果
    text = '\n'.join(result_lines)

    # 清理多余空行（3个以上连续空行→2个）
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # 附加标签行
    if all_tags:
        unique_tags = list(dict.fromkeys(all_tags))
        text += '\n\n' + ' '.join(unique_tags)

    return text


def _is_single_numbered_line(line: str) -> bool:
    """判断是否为单独的编号行（行内只有一个编号项）"""
    if not re.match(r'^\d+[.、)）]\s*\S', line):
        return False
    # 如果行内还有其他编号（说明多个问题挤在一行），不算单独行
    remaining = re.sub(r'^\d+[.、)）]\s*', '', line, count=1)
    if re.search(r'\s+\d+[.、)）]\s*\S', remaining):
        return False
    return True


def _format_long_line(line: str) -> str:
    """
    对单行长文本进行智能拆分格式化

    处理优先级：
    1. emoji 分段标记 → 换行
    2. 面试轮次关键词 → 换行 + 加粗
    3. 编号列表 → 拆分为每行一个
    4. 复选框列表 → 拆分
    5. 无编号的问句长段落 → 按问句边界拆分
    """
    # ====== 步骤1：emoji 分段标记换行 ======
    # 支持常见面经 emoji：📍🕐💻❓🙌⏰🕒 等
    line = re.sub(r'([📍🕐💻❓🙌⏰🕒🔹🔸▶️➡️])', r'\n\1', line)

    # ====== 步骤2：面试轮次关键词分段 ======
    # 匹配 "一面(" "一面 " "一面：" 等形式，前面要有非空字符
    round_keywords = (
        r'一面|二面|三面|四面|五面|六面|七面|'
        r'HR面|hr面|电话面|笔试|初面|复面|终面'
    )
    # 在轮次关键词前换行并加粗，仅当前面有内容时
    line = re.sub(
        rf'(?<=\S)\s+((?:{round_keywords})[\s(（:：])',
        r'\n\n**\1**',
        line,
    )
    # 处理行首的轮次关键词（如直接以 "一面 xxx" 开头）
    line = re.sub(
        rf'^((?:{round_keywords})[\s(（:：])',
        r'**\1**',
        line,
    )

    # ====== 步骤3：编号列表拆分 ======
    # 将 "xxx 1.aaa 2.bbb 3.ccc" → "xxx\n1.aaa\n2.bbb\n3.ccc"
    # 关键：编号前面必须有非空字符 + 空格，避免误拆 "1.5h" 这类文本
    numbered_pattern = r'(?<=\S)\s+(\d+[.、)）]\s*(?!\d))'
    if re.search(numbered_pattern, line):
        line = re.sub(numbered_pattern, r'\n\1', line)

    # ====== 步骤4：复选框列表拆分 ======
    line = re.sub(r'(?<=\S)\s+(\[[ Xx]\]\s*)', r'\n\1', line)

    # ====== 步骤5：无编号的问句长段落拆分 ======
    # 处理没有编号但多个问题挤在一行的情况
    # 拆分后的每一子行单独处理
    sub_lines = line.split('\n')
    final_lines = []

    for sub in sub_lines:
        sub = sub.strip()
        if not sub:
            continue

        # 如果子行仍然很长且包含多个问句，按问句边界拆分
        if len(sub) > 100 and not re.match(r'^\d+[.、)）]', sub):
            split_result = _split_by_question_boundaries(sub)
            final_lines.extend(split_result)
        else:
            final_lines.append(sub)

    return '\n'.join(final_lines)


def _split_by_question_boundaries(text: str) -> list[str]:
    """
    对无编号的长段落，按问句边界拆分

    识别逻辑：
    - 以 "？" 或 "?" 结尾的句子为一个独立问题
    - 带场景描述的问句（如"如果xxx，怎么xxx？"）保持完整
    - 非问句的描述性段落（面试感想等）保持完整不拆
    """
    # 统计问号数量，太少则不拆
    question_marks = len(re.findall(r'[？?]', text))
    if question_marks < 2:
        return [text]

    # 按问句边界拆分：在"？"或"?"后面跟着空格+新内容时断行
    # 但不拆分括号内的问号
    segments = []
    current = []
    # 按空格分词，然后按问号聚合
    parts = re.split(r'([？?])', text)

    for i, part in enumerate(parts):
        current.append(part)
        if part in ('？', '?'):
            # 这是一个问号，检查后面是否还有内容
            if i + 1 < len(parts):
                remaining = parts[i + 1].strip()
                # 如果后面还有实质内容，则断行
                if remaining and len(remaining) > 3:
                    segments.append(''.join(current).strip())
                    current = []

    # 剩余内容
    if current:
        remainder = ''.join(current).strip()
        if remainder:
            segments.append(remainder)

    # 过滤空段
    segments = [s for s in segments if s.strip()]

    # 如果拆分后只有一段或更少，返回原文
    if len(segments) <= 1:
        return [text]

    return segments


def format_entry_markdown(entry: InterviewEntry) -> str:
    """将单个面经条目格式化为 Markdown"""
    lines = []

    # 标题
    lines.append(f'## {entry.title}')
    lines.append('')

    # 元信息表格
    lines.append('| 属性 | 值 |')
    lines.append('| --- | --- |')
    lines.append(f'| 作者 | {entry.author} |')
    if entry.link:
        lines.append(f'| 链接 | [{entry.link}]({entry.link}) |')
    if entry.department:
        lines.append(f'| 部门 | {entry.department} |')
    if entry.round_info:
        lines.append(f'| 面试轮次 | {entry.round_info} |')
    if entry.interview_time:
        lines.append(f'| 面试时间 | {entry.interview_time} |')
    if entry.tags:
        lines.append(f'| 标签 | {", ".join(entry.tags)} |')
    lines.append('')

    # 正文内容（结构化分类处理）
    content = entry.content.strip()
    if content:
        lines.append('### 面试内容')
        lines.append('')
        lines.append(classify_and_restructure_content(content, entry.tags))
    lines.append('')

    return '\n'.join(lines)


def write_classified_output(
    classified: dict,
    output_dir: str,
    file_meta: dict,
):
    """
    按分类结构写入文件

    输出结构:
    output_dir/
    ├── 前端/
    │   ├── 腾讯/
    │   │   ├── _index.md        (公司级索引)
    │   │   ├── 腾讯-wxg.md      (按部门归档)
    │   │   ├── 腾讯-csig.md
    │   │   └── 腾讯-通用.md
    │   ├── 字节跳动/
    │   │   └── ...
    │   └── _index.md            (岗位级索引)
    └── _summary.md              (总汇索引)
    """
    os.makedirs(output_dir, exist_ok=True)

    summary_lines = []
    summary_lines.append('# 面经数据汇总')
    summary_lines.append('')
    if file_meta:
        summary_lines.append('## 数据来源')
        summary_lines.append('')
        for key, value in file_meta.items():
            summary_lines.append(f'- **{key}**: {value}')
        summary_lines.append('')
    summary_lines.append(f'- **处理时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    summary_lines.append('')

    total_count = 0

    for position, companies in sorted(classified.items()):
        position_dir = os.path.join(output_dir, position)
        os.makedirs(position_dir, exist_ok=True)

        position_index_lines = []
        position_index_lines.append(f'# {position} 面经索引')
        position_index_lines.append('')
        position_count = 0

        for company, entries in sorted(companies.items(), key=lambda x: -len(x[1])):
            company_dir = os.path.join(position_dir, company)
            os.makedirs(company_dir, exist_ok=True)

            # 对腾讯等大公司按部门细分
            if company == '腾讯':
                dept_groups = defaultdict(list)
                for entry in entries:
                    dept = entry.department if entry.department else '通用'
                    dept_groups[dept].append(entry)

                company_index_lines = []
                company_index_lines.append(f'# {company} {position} 面经索引')
                company_index_lines.append('')
                company_index_lines.append(f'共 **{len(entries)}** 篇面经')
                company_index_lines.append('')

                for dept, dept_entries in sorted(dept_groups.items(), key=lambda x: -len(x[1])):
                    filename = f'{company}-{dept}.md'
                    filepath = os.path.join(company_dir, filename)

                    file_lines = []
                    file_lines.append(f'# {company} - {dept} {position}面经')
                    file_lines.append('')
                    file_lines.append(f'共 **{len(dept_entries)}** 篇')
                    file_lines.append('')

                    for entry in dept_entries:
                        file_lines.append(format_entry_markdown(entry))
                        file_lines.append('---')
                        file_lines.append('')

                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(file_lines))

                    company_index_lines.append(f'### {dept}（{len(dept_entries)} 篇）')
                    company_index_lines.append('')
                    for entry in dept_entries:
                        company_index_lines.append(f'- [{entry.title}]({filename}) - {entry.author}')
                    company_index_lines.append('')

                with open(os.path.join(company_dir, '_index.md'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join(company_index_lines))

            else:
                # 非大公司直接归为一个文件
                filename = f'{company}.md'
                filepath = os.path.join(company_dir, filename)

                file_lines = []
                file_lines.append(f'# {company} {position}面经')
                file_lines.append('')
                file_lines.append(f'共 **{len(entries)}** 篇')
                file_lines.append('')

                for entry in entries:
                    file_lines.append(format_entry_markdown(entry))
                    file_lines.append('---')
                    file_lines.append('')

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(file_lines))

                # 写公司级索引
                company_index_lines = []
                company_index_lines.append(f'# {company} {position}面经索引')
                company_index_lines.append('')
                company_index_lines.append(f'共 **{len(entries)}** 篇')
                company_index_lines.append('')
                for entry in entries:
                    company_index_lines.append(f'- [{entry.title}]({filename}) - {entry.author}')
                company_index_lines.append('')

                with open(os.path.join(company_dir, '_index.md'), 'w', encoding='utf-8') as f:
                    f.write('\n'.join(company_index_lines))

            position_count += len(entries)
            position_index_lines.append(f'## {company}（{len(entries)} 篇）')
            position_index_lines.append('')
            position_index_lines.append(f'📁 [{company}/](./{company}/)')
            position_index_lines.append('')

        position_index_lines.insert(2, f'共 **{position_count}** 篇面经\n')

        with open(os.path.join(position_dir, '_index.md'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(position_index_lines))

        total_count += position_count
        summary_lines.append(f'## {position}（{position_count} 篇）')
        summary_lines.append('')
        for company in sorted(companies.keys(), key=lambda x: -len(companies[x])):
            count = len(companies[company])
            summary_lines.append(f'- **{company}**: {count} 篇 → 📁 `{position}/{company}/`')
        summary_lines.append('')

    summary_lines.insert(2, f'共处理 **{total_count}** 篇有效面经\n')

    with open(os.path.join(output_dir, '_summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary_lines))

    return total_count


def generate_stats(
    classified: dict,
    entries: list[InterviewEntry],
    original_count: int,
    valid_count: int,
    dedup_count: int,
) -> str:
    """生成处理统计报告"""
    lines = []
    lines.append('=' * 50)
    lines.append('面经处理统计报告')
    lines.append('=' * 50)
    lines.append(f'原始条目数: {original_count}')
    lines.append(f'有效面经数: {valid_count}')
    lines.append(f'去重后条目数: {dedup_count}')
    lines.append(f'过滤无效条目数: {original_count - valid_count}')
    lines.append(f'去重条目数: {valid_count - dedup_count}')
    lines.append('')
    lines.append('分类统计:')
    for position, companies in sorted(classified.items()):
        total = sum(len(entries) for entries in companies.values())
        lines.append(f'  {position}: {total} 篇')
        for company, company_entries in sorted(companies.items(), key=lambda x: -len(x[1])):
            lines.append(f'    - {company}: {len(company_entries)} 篇')
    lines.append('=' * 50)

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='面经数据解析与分类处理工具',
    )
    parser.add_argument(
        'input_file',
        help='牛客网导出的 Markdown 文件路径',
    )
    parser.add_argument(
        '--output', '-o',
        default='./interview-archive',
        help='输出目录路径（默认: ./interview-archive）',
    )
    parser.add_argument(
        '--position', '-p',
        default='前端',
        help='默认岗位名称（默认: 前端）',
    )

    args = parser.parse_args()

    if not os.path.isfile(args.input_file):
        print(f'错误: 文件不存在 - {args.input_file}', file=sys.stderr)
        sys.exit(1)

    print(f'正在解析文件: {args.input_file}')

    # 1. 解析文件
    file_meta, entries = parse_markdown_file(args.input_file)
    original_count = len(entries)
    print(f'解析到 {original_count} 个条目')

    # 2. 过滤无效条目
    valid_entries = [e for e in entries if e.is_valid]
    valid_count = len(valid_entries)
    print(f'有效面经: {valid_count} 篇（过滤 {original_count - valid_count} 篇无效条目）')

    # 3. 去重
    unique_entries = deduplicate_entries(valid_entries)
    dedup_count = len(unique_entries)
    print(f'去重后: {dedup_count} 篇（去除 {valid_count - dedup_count} 篇重复条目）')

    # 4. 分类
    classified = classify_entries(unique_entries, default_position=args.position)

    # 5. 输出
    output_dir = os.path.abspath(args.output)
    total = write_classified_output(classified, output_dir, file_meta)
    print(f'\n输出目录: {output_dir}')
    print(f'共写入 {total} 篇面经')

    # 6. 统计报告
    stats = generate_stats(classified, unique_entries, original_count, valid_count, dedup_count)
    print(f'\n{stats}')


if __name__ == '__main__':
    main()
