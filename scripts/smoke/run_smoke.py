#!/usr/bin/env python3
# ==============================================================================
# input_build smoke runner | scripts/smoke/run_smoke.py
#
# 读取 smoke_env.yaml（平台环境配置）+ cases.yaml（平台无关用例），逐用例：
#   1. 在 runs/<case>/ 下重建工作目录，落盘输入文件（支持 {{var}} 模板替换）；
#   2. 按 env 的 shell_prefix + setup + launcher 组装命令并执行（强制 timeout，
#      超时杀进程树）；
#   3. 按 cases.yaml 的 asserts 做物理断言 —— 绝不只看退出码：
#      LAMMPS 报错时退出码也是 0，必须 not_grep 日志中的 ERROR 行；
#   4. 输出 Markdown 报告（stdout + runs/smoke_report.md）。
#
# 依赖：纯 stdlib。若环境装有 PyYAML 则优先用 PyYAML 解析 .yaml；否则回退到
#       内置 YAML 子集解析器（子集语法见 README 附录 A）。--env-file /
#       --cases-file 传入 .json 时按扩展名自动切换 json.load。
#
# 用法：
#   python run_smoke.py --list                      # 列出并校验全部用例（不自启算）
#   python run_smoke.py                             # 跑全部用例
#   python run_smoke.py --only si_relax,h2_freq     # 只跑指定用例
#   python run_smoke.py --env wsl-local --report runs/my.md
# ==============================================================================

from __future__ import annotations

import argparse
import datetime
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

SMOKE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(SMOKE_DIR, "runs")

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


# ==============================================================================
# 1. YAML 子集解析器（无 PyYAML 时的回退；语法子集见 README 附录 A）
# ==============================================================================

class YamlSubsetError(ValueError):
    """内置 YAML 子集解析失败。"""


def _strip_comment(line: str) -> str:
    """去掉行尾注释；单/双引号内的 # 不算注释。"""
    out = []
    in_sq = in_dq = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_dq:
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch == "#" and not in_sq and not in_dq:
            if i == 0 or line[i - 1] in " \t":
                break
        out.append(ch)
    return "".join(out)


def _tokenize(raw_lines):
    """把原始行变成 (indent, content, lineno, literal|None) 列表。

    处理 `key: |` / `key: |-` 字面块（literal block），块内容原样保留
    （不去注释、不去空白），这是内联 INCAR/inp 文件的关键。
    """
    items = []
    i, n = 0, len(raw_lines)
    lit_re = re.compile(r"^(?P<head>.*?):\s*\|(?P<strip>-)?\s*$")
    while i < n:
        ln = raw_lines[i]
        i += 1
        if not ln.strip():
            continue
        stripped = ln.lstrip(" ")
        if stripped.startswith("#"):
            continue
        indent = len(ln) - len(stripped)
        content = _strip_comment(ln).rstrip()
        if not content.strip():
            continue
        content = content.strip()
        m = lit_re.match(content)
        if m:
            block = []
            while i < n:
                bl = raw_lines[i]
                if bl.strip() == "":
                    block.append("")
                    i += 1
                    continue
                bindent = len(bl) - len(bl.lstrip(" "))
                if bindent <= indent:
                    break
                block.append(bl)
                i += 1
            nonempty = [b for b in block if b.strip()]
            mind = min(len(b) - len(b.lstrip(" ")) for b in nonempty) if nonempty else 0
            lit = "\n".join(b[mind:] for b in block)
            lit = lit.rstrip("\n")
            if not m.group("strip"):
                lit += "\n"
            items.append((indent, m.group("head").strip() + ":", i, lit))
        else:
            items.append((indent, content, i, None))
    return items


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == s[-1] == '"':
        body = s[1:-1]
        return (body.replace("\\\\", "\x00").replace("\\n", "\n")
                    .replace("\\t", "\t").replace('\\"', '"').replace("\x00", "\\"))
    return s


def _bare_scalar(s: str):
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return _unquote(s)


def _flow(s: str):
    """解析 flow 集合 `[a, b]` / `{k: v}`（元素限标量，可嵌套集合）。"""
    pos = 0

    def err(msg):
        raise YamlSubsetError(f"flow 解析失败: {msg} :: {s!r}")

    def skip_ws():
        nonlocal pos
        while pos < len(s) and s[pos] in " \t":
            pos += 1

    def parse_value():
        nonlocal pos
        skip_ws()
        if pos >= len(s):
            err("意外结束")
        ch = s[pos]
        if ch == "[":
            pos += 1
            out = []
            skip_ws()
            if pos < len(s) and s[pos] == "]":
                pos += 1
                return out
            while True:
                out.append(parse_value())
                skip_ws()
                if pos >= len(s):
                    err("缺少 ]")
                if s[pos] == ",":
                    pos += 1
                    continue
                if s[pos] == "]":
                    pos += 1
                    return out
                err(f"期望 , 或 ] ，得到 {s[pos]!r}")
        if ch == "{":
            pos += 1
            out = {}
            skip_ws()
            if pos < len(s) and s[pos] == "}":
                pos += 1
                return out
            while True:
                skip_ws()
                start = pos
                if s[pos] in "'\"":
                    key = parse_value()
                else:
                    while pos < len(s) and s[pos] not in ":,}":
                        pos += 1
                    key = s[start:pos].strip()
                skip_ws()
                if pos >= len(s) or s[pos] != ":":
                    err("map 缺少 :")
                pos += 1
                out[key] = parse_value()
                skip_ws()
                if pos >= len(s):
                    err("缺少 }")
                if s[pos] == ",":
                    pos += 1
                    continue
                if s[pos] == "}":
                    pos += 1
                    return out
                err(f"期望 , 或 }} ，得到 {s[pos]!r}")
        if ch in "'\"":
            q = ch
            pos += 1
            start = pos
            buf = []
            while pos < len(s):
                if q == '"' and s[pos] == "\\" and pos + 1 < len(s):
                    buf.append(s[pos:pos + 2])
                    pos += 2
                    continue
                if s[pos] == q:
                    if q == "'" and pos + 1 < len(s) and s[pos + 1] == "'":
                        buf.append("''")
                        pos += 2
                        continue
                    raw = "".join(buf) + s[start:pos] if buf else s[start:pos]
                    pos += 1
                    return _unquote(q + raw + q)
                pos += 1
            err("引号未闭合")
        start = pos
        while pos < len(s) and s[pos] not in ",]}#":
            pos += 1
        token = s[start:pos].strip()
        if token == "":
            err("空标量")
        return _bare_scalar(token)

    val = parse_value()
    skip_ws()
    if pos != len(s):
        err("flow 末尾有多余字符")
    return val


def _scalar(s: str):
    s = s.strip()
    if s.startswith("[") or s.startswith("{"):
        return _flow(s)
    return _bare_scalar(s)


def _parse_block(items, i, indent):
    first = items[i][1]
    if first == "-" or first.startswith("- "):
        return _parse_list(items, i, indent)
    return _parse_map(items, i, indent)


def _parse_map(items, i, indent):
    out = {}
    while i < len(items):
        ind, content, lineno, lit = items[i]
        if ind < indent:
            break
        if ind > indent:
            raise YamlSubsetError(f"第 {lineno} 行缩进异常: {content!r}")
        if content == "-" or content.startswith("- "):
            raise YamlSubsetError(f"第 {lineno} 行在 map 中出现列表项: {content!r}")
        key, sep, rest = content.partition(":")
        if not sep:
            raise YamlSubsetError(f"第 {lineno} 行缺少 ':' : {content!r}")
        key = key.strip()
        rest = rest.strip()
        if lit is not None:
            out[key] = lit
            i += 1
        elif rest == "":
            if i + 1 < len(items) and items[i + 1][0] > ind:
                val, i = _parse_block(items, i + 1, items[i + 1][0])
                out[key] = val
            else:
                out[key] = None
                i += 1
        else:
            out[key] = _scalar(rest)
            i += 1
    return out, i


_MAP_ITEM_RE = re.compile(r"^[^'\"\[\]{}\s][^:]*:\s")


def _parse_list(items, i, indent):
    out = []
    while i < len(items):
        ind, content, lineno, lit = items[i]
        if ind < indent:
            break
        if ind > indent:
            raise YamlSubsetError(f"第 {lineno} 行缩进异常: {content!r}")
        if not (content == "-" or content.startswith("- ")):
            break
        rest = content[1:].strip()
        if rest == "":
            if i + 1 < len(items) and items[i + 1][0] > ind:
                val, i = _parse_block(items, i + 1, items[i + 1][0])
                out.append(val)
            else:
                out.append(None)
                i += 1
        elif lit is not None:
            raise YamlSubsetError(f"第 {lineno} 行：列表项内不支持字面块 '|'")
        elif _MAP_ITEM_RE.match(rest):
            # `- key: value` 形式：把本行改写成缩进 +2 的 map 首行再递归
            items[i] = (ind + 2, rest, lineno, None)
            val, i = _parse_map(items, i, ind + 2)
            out.append(val)
        else:
            out.append(_scalar(rest))
            i += 1
    return out, i


def parse_yaml_subset(text: str):
    """解析 YAML 子集（块 map / 块 list / 字面块 / flow 集合 / 标量）。"""
    items = _tokenize(text.splitlines())
    if not items:
        return None
    obj, i = _parse_block(items, 0, items[0][0])
    if i != len(items):
        raise YamlSubsetError(f"第 {items[i][2]} 行起无法归入文档结构")
    return obj


def load_structured(path: str):
    """按扩展名加载 .json 或 .yaml；yaml 优先 PyYAML，回退内置子集解析器。"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        return json.loads(text)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return parse_yaml_subset(text)


# ==============================================================================
# 2. 模板与上下文
# ==============================================================================

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def build_context(env: dict) -> dict:
    """把 env 的 codes/data 拍平成 {{var}} 替换表。"""
    ctx = {}
    for section in ("codes", "data"):
        for k, v in (env.get(section) or {}).items():
            ctx[k] = v
    data = env.get("data") or {}
    if data.get("lammps_potentials") and data.get("al_eam_file"):
        ctx["al_eam_path"] = (str(data["lammps_potentials"]).rstrip("/")
                              + "/" + str(data["al_eam_file"]))
    return ctx


def render(text: str, ctx: dict, where: str = "") -> str:
    def rep(m):
        key = m.group(1)
        if key not in ctx:
            raise KeyError(f"模板变量 {{{{{key}}}}} 未在 env 中定义（{where}）")
        return str(ctx[key])
    return _VAR_RE.sub(rep, text)


# ==============================================================================
# 3. 用例执行
# ==============================================================================

def _kill_tree(proc: subprocess.Popen) -> None:
    """超时后尽最大努力杀进程树（Windows 用 taskkill /T）。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _number(value, label, errs):
    try:
        number = float(value)
    except (TypeError, ValueError):
        errs.append(f"{label} 必须是数值，得到 {value!r}")
        return None
    if not math.isfinite(number):
        errs.append(f"{label} 必须是有限数值，得到 {value!r}")
        return None
    return number


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def _validate_assertion(assertion: dict, index: int) -> list:
    errs = []
    prefix = f"assert[{index}]"
    atype = assertion.get("type")
    allowed = ("file_exists", "grep", "not_grep", "regex_number", "xyz_angle")
    if not atype:
        return [f"{prefix} 缺少 type"]
    if atype not in allowed:
        return [f"{prefix} 未知 type: {atype!r}"]

    if not assertion.get("path"):
        errs.append(f"{prefix} ({atype}) 缺少 path")
    if atype in ("grep", "not_grep", "regex_number"):
        pattern = assertion.get("pattern")
        if not pattern:
            errs.append(f"{prefix} ({atype}) 缺少 pattern")
        else:
            try:
                compiled = re.compile(str(pattern))
                if atype == "regex_number" and compiled.groups < 1:
                    errs.append(f"{prefix} regex_number pattern 必须含数值捕获组")
            except re.error as exc:
                errs.append(f"{prefix} pattern 不是合法正则表达式: {exc}")

    if atype == "file_exists" and "min_size" in assertion:
        size = _number(assertion["min_size"], f"{prefix}.min_size", errs)
        if size is not None and (size < 0 or not size.is_integer()):
            errs.append(f"{prefix}.min_size 必须是非负整数")

    if atype == "regex_number":
        if assertion.get("occurrence", "last") not in ("first", "last"):
            errs.append(f"{prefix}.occurrence 必须是 first 或 last")
        divide = _number(assertion.get("divide_by", 1), f"{prefix}.divide_by", errs)
        if divide == 0:
            errs.append(f"{prefix}.divide_by 不得为 0")
        bounds = {}
        for key in ("min", "max", "abs_min"):
            if key in assertion:
                bounds[key] = _number(assertion[key], f"{prefix}.{key}", errs)
        if bounds.get("abs_min") is not None and bounds["abs_min"] < 0:
            errs.append(f"{prefix}.abs_min 必须 >= 0")
        if (bounds.get("min") is not None and bounds.get("max") is not None
                and bounds["min"] > bounds["max"]):
            errs.append(f"{prefix}.min 不得大于 max")

    if atype == "xyz_angle":
        atoms = assertion.get("atoms")
        if (not isinstance(atoms, list) or len(atoms) != 3
                or not all(isinstance(x, int) and x > 0 for x in atoms)):
            errs.append(f"{prefix}.atoms 必须是 3 个正整数（1-based）")
        lo = _number(assertion.get("min"), f"{prefix}.min", errs)
        hi = _number(assertion.get("max"), f"{prefix}.max", errs)
        if lo is not None and hi is not None and lo > hi:
            errs.append(f"{prefix}.min 不得大于 max")
    return errs


def validate_case(case: dict, ctx: dict | None = None) -> list:
    """schema 级校验，返回错误信息列表（空 = 通过）。"""
    errs = []
    for key in ("name", "code", "run"):
        if not case.get(key):
            errs.append(f"缺少必填字段 {key!r}")
    if case.get("code") not in ("vasp", "cp2k", "lammps"):
        errs.append(f"code 必须是 vasp/cp2k/lammps，得到 {case.get('code')!r}")
    if not case.get("files") and not case.get("setup_cmds"):
        errs.append("files 与 setup_cmds 至少给其一")
    assertions = case.get("asserts")
    if not isinstance(assertions, list) or not assertions:
        errs.append("asserts 必须是至少含 1 个物理断言的列表")
    else:
        for index, assertion in enumerate(assertions):
            if not isinstance(assertion, dict):
                errs.append(f"assert[{index}] 必须是 map，得到 {assertion!r}")
            else:
                errs.extend(_validate_assertion(assertion, index))
    if ctx is not None:
        missing = set()
        for value in _iter_strings(case):
            for key in _VAR_RE.findall(value):
                if key not in ctx:
                    missing.add(key)
        if case.get("potcar") and "vasp_potcars" not in ctx:
            missing.add("vasp_potcars")
        for key in sorted(missing):
            errs.append(f"模板变量 {{{{{key}}}}} 未在所选 env 中定义")
    return errs


def run_case(case: dict, env: dict, ctx: dict) -> dict:
    name = case["name"]
    workdir = os.path.join(RUNS_DIR, name)
    if os.path.isdir(workdir):
        shutil.rmtree(workdir)
    os.makedirs(workdir)

    result = {"name": name, "code": case["code"], "status": "ERROR",
              "duration": 0.0, "failures": [], "workdir": workdir}

    try:
        # 1) 落盘输入文件
        for fname, content in (case.get("files") or {}).items():
            dst = os.path.join(workdir, fname)
            os.makedirs(os.path.dirname(dst) or workdir, exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as f:
                f.write(render(content, ctx, where=f"{name}:{fname}"))

        # 2) 组装命令
        setup_cmds = [render(c, ctx, where=name)
                      for c in (case.get("setup_cmds") or [])]
        if case.get("potcar"):
            if "vasp_potcars" not in ctx:
                raise KeyError(f"{name}: 需要 potcar 但 env 未定义 data.vasp_potcars")
            parts = " ".join(f"{str(ctx['vasp_potcars']).rstrip('/')}/{el}/POTCAR"
                             for el in case["potcar"])
            setup_cmds.append(f"cat {parts} > POTCAR")
        run_cmd = render(case["run"], ctx, where=name)
        launcher = (env.get("launcher") or {}).get(case["code"], "direct")
        if launcher and launcher != "direct":
            run_cmd = launcher.format(cmd=run_cmd)
        omp = str((env.get("omp_num_threads") or {}).get(case["code"], "1"))

        exec_root = (env.get("exec") or {}).get("work_root", "")
        exec_dir = (str(exec_root).rstrip("/") + "/" + name) if exec_root else workdir

        parts = []
        if env.get("setup"):
            parts.append(str(env["setup"]))
        parts.append(f"export OMP_NUM_THREADS={omp}")
        parts.append(f"cd {exec_dir}")
        parts.extend(setup_cmds)
        parts.append(run_cmd)
        full_cmd = " && ".join(parts)

        prefix = env.get("shell_prefix") or ["bash", "-lc"]
        argv = list(prefix) + [full_cmd]

        # 3) 执行（强制 timeout）
        timeout = int(case.get("timeout") or env.get("timeout_default") or 1200)
        log_path = os.path.join(workdir, "runner.log")
        t0 = time.time()
        timed_out = False
        with open(log_path, "w", encoding="utf-8", newline="\n") as lf:
            lf.write(f"# smoke case: {name}\n# argv: {argv!r}\n# cmd:\n{full_cmd}\n")
            lf.write("# " + "=" * 70 + "\n")
            lf.flush()
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(argv, stdout=lf,
                                    stderr=subprocess.STDOUT, **kwargs)
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                rc = None
                timed_out = True
        result["duration"] = round(time.time() - t0, 1)
        result["log"] = log_path

        if timed_out:
            result["status"] = "TIMEOUT"
            result["failures"].append(f"超过 timeout={timeout}s，已杀进程树")
            return result
        if rc != 0 and not case.get("allow_nonzero_exit"):
            result["failures"].append(
                f"进程退出码 {rc}（allow_nonzero_exit 未开启；"
                f"注意 LAMMPS/部分代码报错也可能退出 0，退出码只是辅助）")

        # 4) 物理断言
        result["failures"].extend(check_asserts(case, workdir))
        result["status"] = "PASS" if not result["failures"] else "FAIL"
    except Exception as exc:  # noqa: BLE001 —— smoke runner 不因单用例异常中断
        result["status"] = "ERROR"
        result["failures"].append(f"runner 异常: {exc!r}")
    return result


# ==============================================================================
# 4. 断言
# ==============================================================================

def _resolve(workdir: str, pattern: str) -> list:
    return sorted(glob.glob(os.path.join(workdir, pattern)))


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _last_xyz_frame(path: str) -> list:
    """返回 XYZ（轨迹）文件最后一帧的坐标列表 [(x, y, z), ...]。"""
    lines = _read(path).splitlines()
    idx = 0
    frames = []
    while idx < len(lines):
        if not lines[idx].strip():
            idx += 1
            continue
        n = int(lines[idx].split()[0])
        frames.append(lines[idx + 2: idx + 2 + n])
        idx += n + 2
    if not frames:
        raise ValueError("未找到任何 XYZ 帧")
    coords = []
    for ln in frames[-1]:
        p = ln.split()
        coords.append((float(p[-3]), float(p[-2]), float(p[-1])))
    return coords


def _angle_deg(a, b, c) -> float:
    """a-b-c 夹角（b 为顶点），单位度。"""
    v1 = [a[k] - b[k] for k in range(3)]
    v2 = [c[k] - b[k] for k in range(3)]
    n1 = math.sqrt(sum(x * x for x in v1))
    n2 = math.sqrt(sum(x * x for x in v2))
    cosang = sum(v1[k] * v2[k] for k in range(3)) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosang))))


def check_asserts(case: dict, workdir: str) -> list:
    failures = []
    for a in case.get("asserts") or []:
        atype = a["type"]
        label = a.get("note") or atype
        try:
            if atype == "file_exists":
                hits = _resolve(workdir, a["path"])
                if not hits:
                    failures.append(f"[{label}] 文件不存在: {a['path']}")
                else:
                    min_size = int(a.get("min_size", 0))
                    small = [h for h in hits if os.path.getsize(h) < min_size]
                    if small:
                        failures.append(
                            f"[{label}] 文件小于 {min_size}B: "
                            + ", ".join(os.path.basename(h) for h in small))

            elif atype in ("grep", "not_grep"):
                hits = _resolve(workdir, a["path"])
                if not hits:
                    failures.append(f"[{label}] 文件不存在: {a['path']}")
                    continue
                text = _read(hits[0])
                found = re.search(a["pattern"], text) is not None
                if atype == "grep" and not found:
                    failures.append(
                        f"[{label}] {os.path.basename(hits[0])} 中未匹配到 "
                        f"/{a['pattern']}/")
                if atype == "not_grep" and found:
                    failures.append(
                        f"[{label}] {os.path.basename(hits[0])} 中出现了禁止模式 "
                        f"/{a['pattern']}/")

            elif atype == "regex_number":
                hits = _resolve(workdir, a["path"])
                if not hits:
                    failures.append(f"[{label}] 文件不存在: {a['path']}")
                    continue
                text = _read(hits[0])
                matches = list(re.finditer(a["pattern"], text))
                if not matches:
                    failures.append(
                        f"[{label}] {os.path.basename(hits[0])} 中未匹配到数值模式 "
                        f"/{a['pattern']}/")
                    continue
                m = matches[0] if a.get("occurrence") == "first" else matches[-1]
                value = float(m.group(1)) / float(a.get("divide_by", 1))
                if not math.isfinite(value):
                    failures.append(
                        f"[{label}] 捕获值 {m.group(1)!r} 不是有限数值")
                    continue
                lo, hi, abs_min = a.get("min"), a.get("max"), a.get("abs_min")
                if abs_min is not None and abs(value) < float(abs_min):
                    failures.append(
                        f"[{label}] 数值绝对值 |{value:.6g}| < 下限 {abs_min}")
                elif lo is not None and value < float(lo):
                    failures.append(f"[{label}] 数值 {value:.6g} < 下限 {lo}")
                elif hi is not None and value > float(hi):
                    failures.append(f"[{label}] 数值 {value:.6g} > 上限 {hi}")

            elif atype == "xyz_angle":
                hits = _resolve(workdir, a["path"])
                if not hits:
                    failures.append(f"[{label}] 文件不存在: {a['path']}")
                    continue
                coords = _last_xyz_frame(hits[0])
                ia, ib, ic = (int(x) - 1 for x in a["atoms"])
                angle = _angle_deg(coords[ia], coords[ib], coords[ic])
                lo, hi = float(a["min"]), float(a["max"])
                if not (lo <= angle <= hi):
                    failures.append(
                        f"[{label}] 最后一帧键角 {angle:.2f}° 不在 "
                        f"[{lo}, {hi}] 范围内")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"[{label}] 断言执行异常: {exc!r}")
    return failures


# ==============================================================================
# 5. 报告与 CLI
# ==============================================================================

def build_report(results: list, env_name: str, elapsed: float) -> str:
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    lines = [
        "# input_build smoke 报告",
        "",
        f"- 环境: `{env_name}`",
        f"- 时间: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"- 总计: **{n_pass}/{len(results)} PASS**，耗时 {elapsed:.1f}s",
        "",
        "| 用例 | 代码 | 结果 | 耗时 (s) | 工作目录 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        mark = {"PASS": "✅ PASS", "FAIL": "❌ FAIL",
                "TIMEOUT": "⏱ TIMEOUT", "ERROR": "💥 ERROR"}[r["status"]]
        lines.append(f"| {r['name']} | {r['code']} | {mark} | "
                     f"{r['duration']} | `{r['workdir']}` |")
    bad = [r for r in results if r["status"] != "PASS"]
    if bad:
        lines += ["", "## 失败明细", ""]
        for r in bad:
            lines.append(f"### {r['name']} ({r['status']})")
            for f_ in r["failures"]:
                lines.append(f"- {f_}")
            if r.get("log"):
                lines.append(f"- 运行日志: `{r['log']}`")
            lines.append("")
    return "\n".join(lines)


def cmd_list(cases: list, ctx: dict | None = None) -> int:
    bad = 0
    for c in cases:
        errs = validate_case(c, ctx=ctx)
        n_assert = len(c.get("asserts") or [])
        if errs:
            bad += 1
            print(f"[ERROR] {c.get('name', '?'):24s} schema/env: {'; '.join(errs)}")
        else:
            print(f"[OK] {c['name']:24s} [{c['code']:6s}] asserts={n_assert}  "
                  f"{c.get('description', '')}")
    print(f"\n共 {len(cases)} 个用例，{len(cases) - bad} 个 schema 校验通过")
    return EXIT_OK if bad == 0 else EXIT_FAIL


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        description="input_build smoke runner（详见 scripts/smoke/README.md）")
    ap.add_argument("--env", default=None,
                    help="smoke_env.yaml 中的环境名（默认取文件里的 default）")
    ap.add_argument("--env-file", default=os.path.join(SMOKE_DIR, "smoke_env.yaml"))
    ap.add_argument("--cases-file", default=os.path.join(SMOKE_DIR, "cases.yaml"))
    ap.add_argument("--only", default=None, help="只跑指定用例，逗号分隔")
    ap.add_argument("--list", action="store_true", help="列出并校验用例后退出")
    ap.add_argument("--report", default=None,
                    help="Markdown 报告输出路径（默认 runs/smoke_report.md）")
    args = ap.parse_args(argv)

    env_doc = load_structured(args.env_file)
    cases = load_structured(args.cases_file)
    if not isinstance(cases, list):
        print(f"[ERROR] cases 文件必须是列表: {args.cases_file}", file=sys.stderr)
        return EXIT_USAGE

    names = [c.get("name") for c in cases]
    if len(names) != len(set(names)):
        print("[ERROR] cases 中存在重复 name", file=sys.stderr)
        return EXIT_USAGE

    env_name = args.env or (env_doc or {}).get("default")
    env = (env_doc.get("environments") or {}).get(env_name) if env_doc else None
    if env is None:
        avail = ", ".join((env_doc.get("environments") or {}).keys())
        print(f"[ERROR] 未知环境 {env_name!r}（可用: {avail}）", file=sys.stderr)
        return EXIT_USAGE
    ctx = build_context(env)

    if args.list:
        return cmd_list(cases, ctx=ctx)

    selected = cases
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = [w for w in wanted if w not in names]
        if unknown:
            print(f"[ERROR] 未知用例: {', '.join(unknown)}", file=sys.stderr)
            return EXIT_USAGE
        selected = [c for c in cases if c["name"] in wanted]

    os.makedirs(RUNS_DIR, exist_ok=True)
    t0 = time.time()
    results = []
    for case in selected:
        errs = validate_case(case, ctx=ctx)
        if errs:
            results.append({"name": case.get("name", "?"),
                            "code": case.get("code", "?"), "status": "ERROR",
                            "duration": 0.0, "workdir": "-",
                            "failures": [f"schema 错误: {'; '.join(errs)}"]})
            continue
        print(f"[RUN] {case['name']} ...", flush=True)
        r = run_case(case, env, ctx)
        results.append(r)
        print(f"  -> {r['status']} ({r['duration']}s)", flush=True)
    elapsed = time.time() - t0

    report = build_report(results, env_name, elapsed)
    report_path = args.report or os.path.join(RUNS_DIR, "smoke_report.md")
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report + "\n")
    print()
    print(report)
    print(f"\n报告已写入: {report_path}")

    return EXIT_OK if all(r["status"] == "PASS" for r in results) else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
