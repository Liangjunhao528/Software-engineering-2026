#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小学四则运算题目生成器
用法:
  myapp.py -n 10 -r 10          # 生成10道10以内的题目
  myapp.py -e exercises.txt -a answers.txt  # 批改
"""

import sys
import random
from fractions import Fraction

# ==================== 分数与格式化 ====================

def frac_to_str(f: Fraction) -> str:
    """将 Fraction 转成题目要求的格式: 3/5 或 2'3/8"""
    if f.denominator == 1:
        return str(f.numerator)
    if abs(f.numerator) < f.denominator:
        # 真分数
        return f"{f.numerator}/{f.denominator}"
    # 带分数
    sign = -1 if f.numerator < 0 else 1
    n = abs(f.numerator)
    whole = n // f.denominator
    rem = n % f.denominator
    if rem == 0:
        return str(sign * whole)
    return f"{sign * whole}'{rem}/{f.denominator}"


def parse_number(s: str) -> Fraction:
    """解析 3/5 或 2'3/8 或普通数字为 Fraction"""
    s = s.strip()
    if "'" in s:
        whole_str, frac_str = s.split("'")
        whole = int(whole_str)
        num, den = frac_str.split("/")
        val = Fraction(int(num), int(den))
        if whole < 0:
            return Fraction(whole, 1) - val
        return Fraction(whole, 1) + val
    if "/" in s:
        num, den = s.split("/")
        return Fraction(int(num), int(den))
    return Fraction(int(s), 1)


# ==================== 表达式树 ====================

class Node:
    __slots__ = ("op", "left", "right", "value")

    def __init__(self, value=None, op=None, left=None, right=None):
        self.value = value   # Fraction 或者 None
        self.op = op         # '+', '-', '*', '/'
        self.left = left
        self.right = right


def eval_node(node: Node) -> Fraction:
    if node.op is None:
        return node.value
    l = eval_node(node.left)
    r = eval_node(node.right)
    if node.op == '+':
        return l + r
    if node.op == '-':
        return l - r
    if node.op == '*':
        return l * r
    if node.op == '/':
        return l / r
    raise ValueError("unknown op")


def op_symbol(op):
    return {'+': '+', '-': '-', '*': '×', '/': '÷'}[op]


def node_to_str(node: Node, parent_op=None, is_right=False) -> str:
    """中缀表达式字符串，加必要的括号保持语义"""
    if node.op is None:
        return frac_to_str(node.value)

    # 优先级: +/- = 1, */ = 2
    def prec(op):
        return 1 if op in '+-' else 2

    cur_prec = prec(node.op)
    inner = f"{node_to_str(node.left, node.op, False)} {op_symbol(node.op)} {node_to_str(node.right, node.op, True)}"

    if parent_op is None:
        return inner

    p_prec = prec(parent_op)
    need = False
    if cur_prec < p_prec:
        need = True
    elif cur_prec == p_prec and is_right:
        # 右子表达式同优先级需要加括号（减法/除法非结合；+- 与 -+ 混合也需要）
        need = True
    if need:
        return f"( {inner} )"
    return inner


# ==================== 题目生成 ====================

def random_fraction(r: int) -> Fraction:
    """在 [0, r) 范围内随机生成自然数或真分数"""
    # 随机决定是自然数还是真分数
    if random.random() < 0.5:
        return Fraction(random.randint(0, r - 1), 1)
    # 真分数: 分子 < 分母 < r
    if r <= 2:
        return Fraction(random.randint(0, r - 1), 1)
    den = random.randint(2, r - 1)
    num = random.randint(0, den - 1)
    return Fraction(num, den)


def build_expr(r: int, max_ops: int = 3):
    """递归构建表达式树，返回 (node, val) 或 None"""
    # 随机选运算符数量: 1~3
    target_ops = random.randint(1, max_ops)

    def build(remaining_ops):
        """返回 (node, value)；保证值合法（不产生负数、除法除数非零）
           任一子树失败时返回 (None, None)，由上层检查后向上传递"""
        if remaining_ops == 0:
            v = random_fraction(r)
            return Node(value=v), v

        # 左子树随机分配运算符数量
        left_ops = random.randint(0, remaining_ops - 1)
        right_ops = remaining_ops - 1 - left_ops

        left_node, left_val = build(left_ops)
        if left_node is None:               # 左子树失败，直接向上传递
            return None, None

        right_node, right_val = build(right_ops)
        if right_node is None:              # 右子树失败，直接向上传递
            return None, None

        op = random.choice(['+', '-', '*', '/'])

        if op == '-':
            # 保证 e1 >= e2
            if left_val < right_val:
                left_node, right_node = right_node, left_node
                left_val, right_val = right_val, left_val
            val = left_val - right_val
        elif op == '/':
            # 除数不能为0
            if right_val == 0:
                return None, None
            val = left_val / right_val
        elif op == '*':
            val = left_val * right_val
        else:
            val = left_val + right_val

        return Node(op=op, left=left_node, right=right_node), val

    node, val = build(target_ops)
    if node is None:
        return None
    return node, val


def canon_key(node: Node):
    """
    生成规范键，用于判重
    """
    if node.op is None:
        return ('n', node.value)
    l = canon_key(node.left)
    r = canon_key(node.right)
    if node.op in ('+', '*'):
        # 交换律：排序
        if l > r:
            l, r = r, l
        return (node.op, l, r)
    return (node.op, l, r)


def generate_exercises(n: int, r: int):
    """生成 n 道不重复的题目（优化版：动态检测题目空间耗尽）"""
    exercises = []
    answers = []
    seen = set()
    attempts = 0
    max_attempts = n * 500 + 5000

    # 新增：连续重复计数器，检测题目空间耗尽
    consecutive_duplicates = 0
    max_consecutive_duplicates = 5000   # 连续 5000 次重复即认为空间耗尽

    while len(exercises) < n and attempts < max_attempts:
        attempts += 1
        result = build_expr(r, max_ops=3)
        if result is None:
            continue
        node, val = result
        if val < 0:
            continue
        key = canon_key(node)
        if key in seen:
            consecutive_duplicates += 1
            if consecutive_duplicates >= max_consecutive_duplicates:
                print(f"警告: 连续 {consecutive_duplicates} 次生成重复题目，"
                      f"判断 -r={r} 题目空间已耗尽，提前终止")
                break
            continue
        seen.add(key)
        consecutive_duplicates = 0   # 成功则重置
        expr_str = node_to_str(node)
        exercises.append(f"{expr_str} =")
        answers.append(frac_to_str(val))

    if len(exercises) < n:
        print(f"警告: 尝试 {attempts} 次后仅生成 {len(exercises)} 道题目"
              f"（可能 -r 过小导致题目空间不足）")
    return exercises, answers


# ==================== 文件写出 ====================

def write_exercises(exercises, filename="Exercises.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        for i, e in enumerate(exercises, 1):
            f.write(f"{i}. {e}\n")


def write_answers(answers, filename="Answers.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        for i, a in enumerate(answers, 1):
            f.write(f"{i}. {a}\n")


# ==================== 批改 ====================

def strip_index(line: str) -> str:
    """去掉行首的编号"""
    line = line.strip()
    if not line:
        return ""
    idx = line.find('.')
    if idx != -1 and line[:idx].strip().isdigit():
        return line[idx + 1:].strip()
    return line


def grade(exercise_file: str, answer_file: str, out_file: str = "Grade.txt"):
    with open(exercise_file, "r", encoding="utf-8") as f:
        ex_lines = [l for l in f.read().splitlines() if l.strip()]
    with open(answer_file, "r", encoding="utf-8") as f:
        ans_lines = [l for l in f.read().splitlines() if l.strip()]

    correct = []
    wrong = []

    for i, (ex_line, ans_line) in enumerate(zip(ex_lines, ans_lines), 1):
        expr_str = strip_index(ex_line)
        ans_str = strip_index(ans_line)
        # 去掉末尾的 '=' 和空格
        expr_str = expr_str.rstrip('=').strip()
        try:
            expected = parse_number(ans_str)
        except Exception:
            wrong.append(i)
            continue
        try:
            actual = evaluate_expression(expr_str)
        except Exception:
            wrong.append(i)
            continue
        if expected == actual:
            correct.append(i)
        else:
            wrong.append(i)

    # 若数量不等，多出的算错
    if len(ex_lines) != len(ans_lines):
        longer = max(len(ex_lines), len(ans_lines))
        known = len(correct) + len(wrong)
        for i in range(known + 1, longer + 1):
            wrong.append(i)

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"Correct: {len(correct)} ({', '.join(map(str, correct))})\n")
        f.write(f"Wrong: {len(wrong)} ({', '.join(map(str, wrong))})\n")


# ==================== 表达式求值（用于批改） ====================

def tokenize(s: str):
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c in '+-×÷()':
            tokens.append(c)
            i += 1
        elif c.isdigit() or c == "'":
            # 读取一个数字或分数（可能带 '）
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] in "/'"):
                j += 1
            tokens.append(s[i:j])
            i = j
        else:
            raise ValueError(f"非法字符: {c}")
    return tokens


def evaluate_expression(s: str) -> Fraction:
    """解析并求值中缀表达式，支持带分数 a'b/c、分数 x/y、整数"""
    tokens = tokenize(s)
    pos = [0]

    def peek():
        if pos[0] < len(tokens):
            return tokens[pos[0]]
        return None

    def consume():
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_primary():
        t = peek()
        if t is None:
            raise ValueError("unexpected end")
        if t == '(':
            consume()
            v = parse_expr()
            if peek() != ')':
                raise ValueError("缺少右括号")
            consume()
            return v
        if t in ('+', '-'):
            consume()
            v = parse_primary()
            return v if t == '+' else -v
        # 数字
        consume()
        return parse_number(t)

    def parse_term():
        v = parse_primary()
        while peek() in ('×', '÷'):
            op = consume()
            r = parse_primary()
            if op == '×':
                v = v * r
            else:
                v = v / r
        return v

    def parse_expr():
        v = parse_term()
        while peek() in ('+', '-'):
            op = consume()
            r = parse_term()
            if op == '+':
                v = v + r
            else:
                v = v - r
        return v

    result = parse_expr()
    if pos[0] != len(tokens):
        raise ValueError("表达式未完全解析")
    return result


# ==================== 帮助信息 ====================

HELP = """
小学四则运算题目生成器

用法:
  myapp.py -n <题目数量> -r <数值范围>
      生成题目，写入 Exercises.txt 和 Answers.txt

  myapp.py -e <题目文件> -a <答案文件>
      批改，将结果写入 Grade.txt

参数:
  -n  生成题目的个数（正整数）
  -r  题目中数值的范围（正整数，题目中数值 < r）
  -e  题目文件路径
  -a  答案文件路径

示例:
  myapp.py -n 10 -r 10
  myapp.py -e Exercises.txt -a Answers.txt
"""


# ==================== 主程序 ====================

def handle_args(argv):
    args = {}
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ('-n', '-r', '-e', '-a'):
            if i + 1 >= len(argv):
                print(f"参数 {token} 缺少值")
                print(HELP)
                sys.exit(1)
            args[token] = argv[i + 1]
            i += 2
        elif token in ('-h', '--help'):
            print(HELP)
            sys.exit(0)
        else:
            print(f"未知参数: {token}")
            print(HELP)
            sys.exit(1)
    return args


def main():
    args = handle_args(sys.argv)

    # 生成模式
    if '-n' not in args or '-r' not in args:
        print("生成题目需要同时提供 -n 和 -r 参数")
        print(HELP)
        sys.exit(1)

    if '-e' in args or '-a' in args:
        # 批改模式
        if '-e' not in args or '-a' not in args:
            print("批改模式需要同时提供 -e 和 -a 参数")
            print(HELP)
            sys.exit(1)
        grade(args['-e'], args['-a'])
        print("批改完成，结果已写入 Grade.txt")
        return

    try:
        n = int(args['-n'])
        r = int(args['-r'])
    except ValueError:
        print("-n 和 -r 必须是整数")
        sys.exit(1)

    if n <= 0:
        print("-n 必须为正整数")
        sys.exit(1)
    if r <= 1:
        print("-r 必须是大于1的整数")
        sys.exit(1)

    print(f"正在生成 {n} 道题目（数值范围 0 ~ {r-1}）...")
    exercises, answers = generate_exercises(n, r)
    write_exercises(exercises)
    write_answers(answers)
    print(f"已生成 {len(exercises)} 道题目 -> Exercises.txt")
    print(f"答案已写入 -> Answers.txt")


if __name__ == "__main__":
    main()