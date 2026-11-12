#!/usr/bin/env python3
"""
career-planner-china 保险渠道触发门槛回归测试（SDI-1 整改配套，2026-11-13）

背景
----
ClawHub 线上复扫（2026-11-13，verify career-planner-china --version 2.3.10）判定
decision=fail / security.status=suspicious，finding = **SDI-1 MEDIUM**：

    Insurance-channel workflow can be triggered by the agent's own career
    recommendations, contrary to the manifest's user-interest requirement.

根因：SKILL.md 运行时章节「保险行业入职引导」的「触发条件」写着
「用户表示对保险行业感兴趣，**或推荐方向涉及保险经纪人/保险代理人/保险销售等**」，
且执行逻辑第 1 步是「首先给出职业方向建议（如保险经纪人、保险代理人等）」——
等于把 **agent 自身的推荐结论**当作读取商业渠道清单的开关，
与 frontmatter description 里已经写明的 opt-in 门槛（「仅在用户主动表示对保险行业
感兴趣时触发」）直接冲突。

本 skill 是**提示词驱动**、没有可执行工作流代码，因此官方 remediation 里要求的
"workflow test" 在本库落成**文本一致性断言**（可被脚本机械判定）+ **业务红线守卫**
（防止整改越界把商业披露删掉）。

断言范围
--------
  Test 1  禁止句式：SKILL.md 全文不得出现「agent 推荐 → 触发渠道列表」的残留路径
  Test 2  否定声明：SKILL.md 必须显式声明「agent 自身生成的职业建议不构成触发理由」
          且必须显式声明「无用户侧信号 → 不读取 broker JSON、不展示任何公司/渠道信息」
  Test 3  opt-in 保留：frontmatter description 里的保险渠道 opt-in 关键词
          （仅在用户主动表示对保险行业感兴趣时触发）必须仍在，且仍在 frontmatter 内
  Test 4  执行顺序：执行逻辑第 1 步必须先「确认用户侧信号」，再谈「读取公司列表」
  Test 5  业务红线：安盛天平保险销售有限公司 / 400-860-0058 /
          priority_basis / priority_disclosure / verified / source_url 仍在 SKILL.md 中
  Test 6  受保护区块：description 行、L92-96 商业决策性优先推荐声明、
          「保险推荐处理说明」整段、L282 能力表「保险行业入职引导」行
          —— 与 git HEAD 逐字节一致（一字不删、不弱化）
  Test 7  broker JSON：references/insurance_broker_companies.json 与 git HEAD
          **字节零变化**（sha256 比对）
  Test 8  salary DB：references/salary_database.json 与 git HEAD **字节零变化**
          （sha256 比对；meta.version 之外的任何差异都算失败）
  Test 9  references/ 整目录：与 git HEAD 零差异（覆盖 Test 7 / Test 8 之外的旁档）

退出码：
  0  全部通过
  1  至少一项失败
  2  依赖文件缺失 / git 不可用，无法完成比对
"""
import hashlib
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
BROKER_JSON = os.path.join("references", "insurance_broker_companies.json")
SALARY_DB = os.path.join("references", "salary_database.json")

PASS = "[PASS]"
FAIL = "[FAIL]"

# ---------------------------------------------------------------------------
# Test 1 禁止句式：任何把「agent 自身推荐」当作触发条件的表达都必须消失
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS = [
    # —— 任务书点名的三类 ——
    "或推荐方向涉及",      # SDI-1 原句（L230）
    "推荐方向涉及保险",
    "如适用",              # 保险章节标题里的模糊条件句
    # —— 同类补充：把 agent 推荐结论接到触发条件上的其它写法 ——
    "或推荐涉及保险",
    "推荐方向涉及",
    "涉及保险经纪人",
    "涉及保险代理人",
    "涉及保险销售",
    "首先给出职业方向建议",  # 旧执行逻辑第 1 步：先由 agent 推出保险方向
    "如保险经纪人",
    "在职业方向推荐中，用户表示对保险行业感兴趣",  # 旧触发条件原句
    "如果职业方向是保险",
    "若职业方向为保险",
    "职业方向涉及保险",
    "职业建议涉及保险",
    "职业方向涉及",
    "当推荐方向",
]

# ---------------------------------------------------------------------------
# Test 2 必须保留的否定声明（任一缺失即失败）
# ---------------------------------------------------------------------------
REQUIRED_NEGATIONS = [
    "agent 自身生成的职业建议",
    "不构成",
    "触发理由",
    "一律不构成触发理由",
    "先确认用户侧信号",
    "不读取 `insurance_broker_companies.json`，不展示任何公司/渠道信息",
]

# ---------------------------------------------------------------------------
# Test 3 frontmatter description 必须保留的 opt-in 关键词
# ---------------------------------------------------------------------------
REQUIRED_DESCRIPTION_KEYWORDS = [
    "【可选功能】保险渠道信息查询",
    "仅在用户主动表示对保险行业感兴趣时触发",
    "与上文的个性化职业方向推荐相互独立、不参与其排序",
    "priority_basis 与 priority_disclosure 字段中披露",
]

# ---------------------------------------------------------------------------
# Test 5 业务红线关键词（一个都不许消失）
# ---------------------------------------------------------------------------
REQUIRED_REDLINE_KEYWORDS = [
    "安盛天平保险销售有限公司",
    "400-860-0058",
    "priority_basis",
    "priority_disclosure",
    "verified",
    "source_url",
]

# ---------------------------------------------------------------------------
# Test 6 受保护区块：必须与 git HEAD 逐字节一致
#   （锚点为 HEAD 版本 SKILL.md 中的原文片段；比对时按"HEAD 中存在 → 当前也存在"判定）
# ---------------------------------------------------------------------------
PROTECTED_BLOCKS = [
    (
        "frontmatter description 行（含【可选功能】保险渠道声明）",
        "description: AI时代职业规划师技能。",
        "关键词：职业规划、选专业、工作建议、做什么工作好、职业转型、AI时代职业、"
        "AI替代、哪些工作会被AI取代。",
    ),
    (
        "L92-96【保险行业入职引导】商业决策性优先推荐声明",
        "【保险行业入职引导】为**业务决策性优先推荐**",
        "verified=true 仅表示该主体公开可查、信息可核验，不代表对特定用户的适配度结论。",
    ),
    (
        "L335+「保险推荐处理说明」整段",
        "### 保险推荐处理说明",
        "**联系方式可见性**：默认隐藏（🔒 标记），用户明确同意后才渲染完整电话。",
    ),
    (
        "L282 能力表「保险行业入职引导」行",
        "| **保险行业入职引导** | 读取 `insurance_broker_companies.json` |",
        "**联系方式需用户明确同意后才展示** |",
    ),
]


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _git(*args):
    """执行 git 命令，返回 (returncode, stdout_bytes)。"""
    proc = subprocess.run(
        ["git", "-C", SKILL_DIR] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout


def _git_blob_bytes(rel_path):
    """取 git HEAD 中某个文件的原始字节；不存在返回 None。"""
    rc, out = _git("cat-file", "blob", "HEAD:%s" % rel_path)
    if rc != 0:
        return None
    return out


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------
def test_no_agent_recommendation_trigger(text):
    print("\nTest 1: SKILL.md must not contain any 'agent recommendation -> trigger' phrasing")
    hits = []
    for pat in FORBIDDEN_PATTERNS:
        n = text.count(pat)
        if n:
            hits.append((pat, n))
    if hits:
        for pat, n in hits:
            print("  %s forbidden pattern still present: %r (x%d)" % (FAIL, pat, n))
        return False
    print("  %s all %d forbidden patterns absent" % (PASS, len(FORBIDDEN_PATTERNS)))
    return True


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------
def test_required_negations(text):
    print("\nTest 2: SKILL.md must explicitly state the negative trigger rule")
    missing = [s for s in REQUIRED_NEGATIONS if s not in text]
    if missing:
        for s in missing:
            print("  %s missing required negative statement: %r" % (FAIL, s))
        return False
    for s in REQUIRED_NEGATIONS:
        print("  %s present: %r" % (PASS, s))
    return True


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------
def test_description_optin_preserved(text):
    print("\nTest 3: frontmatter description opt-in declaration must be preserved")
    parts = text.split("---")
    # parts[0] 为 YAML 之前的空串；parts[1] 为 frontmatter 主体
    if len(parts) < 3:
        print("  %s SKILL.md frontmatter not parseable (missing '---' fences)" % FAIL)
        return False
    frontmatter = parts[1]
    missing = [k for k in REQUIRED_DESCRIPTION_KEYWORDS if k not in frontmatter]
    if missing:
        for k in missing:
            print("  %s missing in frontmatter: %r" % (FAIL, k))
        return False
    for k in REQUIRED_DESCRIPTION_KEYWORDS:
        print("  %s present in frontmatter: %r" % (PASS, k))
    return True


# ---------------------------------------------------------------------------
# Test 4
# ---------------------------------------------------------------------------
def test_execution_order(text):
    print("\nTest 4: execution logic step 1 must gate on user-side signal before reading the list")
    marker = "**执行逻辑**"
    if marker not in text:
        print("  %s '执行逻辑' block not found" % FAIL)
        return False
    block = text.split(marker, 1)[1]
    gate_idx = block.find("先确认用户侧信号")
    read_idx = block.find("读取公司列表：")
    if gate_idx < 0:
        print("  %s execution logic does not gate on user-side signal" % FAIL)
        return False
    if read_idx < 0:
        print("  %s '读取公司列表：' step not found (structure changed?)" % FAIL)
        return False
    if gate_idx > read_idx:
        print("  %s user-side gate appears AFTER the company-list read step" % FAIL)
        return False
    print("  %s user-side gate (offset %d) precedes company-list read (offset %d)"
          % (PASS, gate_idx, read_idx))
    return True


# ---------------------------------------------------------------------------
# Test 5
# ---------------------------------------------------------------------------
def test_business_redlines(text):
    print("\nTest 5: business red-line disclosures must remain in SKILL.md")
    missing = [k for k in REQUIRED_REDLINE_KEYWORDS if k not in text]
    if missing:
        for k in missing:
            print("  %s missing business red-line keyword: %r" % (FAIL, k))
        return False
    for k in REQUIRED_REDLINE_KEYWORDS:
        print("  %s present: %r (x%d)" % (PASS, k, text.count(k)))
    return True


# ---------------------------------------------------------------------------
# Test 6
# ---------------------------------------------------------------------------
def test_protected_blocks_unchanged(text):
    print("\nTest 6: protected blocks must be byte-identical to git HEAD")
    head_bytes = _git_blob_bytes("SKILL.md")
    if head_bytes is None:
        print("  %s cannot read SKILL.md from git HEAD" % FAIL)
        return False
    head_text = head_bytes.decode("utf-8")
    ok = True
    for label, start_marker, end_marker in PROTECTED_BLOCKS:
        s = head_text.find(start_marker)
        e = head_text.find(end_marker, s) if s >= 0 else -1
        if s < 0 or e < 0:
            print("  %s cannot locate protected block in HEAD: %s" % (FAIL, label))
            ok = False
            continue
        head_block = head_text[s:e + len(end_marker)]
        if head_block in text:
            print("  %s unchanged vs HEAD: %s" % (PASS, label))
        else:
            print("  %s protected block was modified: %s" % (FAIL, label))
            ok = False
    return ok


# ---------------------------------------------------------------------------
# Test 7 / Test 8 —— 数据文件字节零变化
# ---------------------------------------------------------------------------
def _test_file_unchanged_vs_head(rel_path, label):
    full = os.path.join(SKILL_DIR, rel_path)
    if not os.path.exists(full):
        print("  %s file not found: %s" % (FAIL, rel_path))
        return False
    head_bytes = _git_blob_bytes(rel_path)
    if head_bytes is None:
        print("  %s cannot read %s from git HEAD" % (FAIL, rel_path))
        return False
    head_sha = _sha256_bytes(head_bytes)
    work_sha = _sha256_file(full)
    print("  head sha256 = %s" % head_sha)
    print("  work sha256 = %s" % work_sha)
    if head_sha != work_sha:
        print("  %s %s CHANGED vs git HEAD" % (FAIL, label))
        return False
    if len(head_bytes) != os.path.getsize(full):
        print("  %s %s size mismatch vs git HEAD" % (FAIL, label))
        return False
    print("  %s %s byte-identical to git HEAD (%d bytes)" % (PASS, label, len(head_bytes)))
    return True


def test_broker_json_unchanged():
    print("\nTest 7: references/insurance_broker_companies.json must be byte-identical to git HEAD")
    return _test_file_unchanged_vs_head(BROKER_JSON, "broker JSON")


def test_salary_db_unchanged():
    print("\nTest 8: references/salary_database.json must be byte-identical to git HEAD")
    return _test_file_unchanged_vs_head(SALARY_DB, "salary DB")


# ---------------------------------------------------------------------------
# Test 9
# ---------------------------------------------------------------------------
def test_references_dir_unchanged():
    print("\nTest 9: references/ directory must have zero diff vs git HEAD")
    rc, out = _git("diff", "--name-only", "HEAD", "--", "references/")
    if rc != 0:
        print("  %s git diff failed for references/" % FAIL)
        return False
    changed = [l for l in out.decode("utf-8").splitlines() if l.strip()]
    if changed:
        for c in changed:
            print("  %s changed under references/: %s" % (FAIL, c))
        return False
    print("  %s no file under references/ differs from git HEAD" % PASS)
    return True


def main():
    print("=" * 68)
    print("career-planner-china 保险渠道触发门槛回归测试 (SDI-1 整改配套)")
    print("=" * 68)
    print("SKILL.md: %s" % SKILL_MD)

    if not os.path.exists(SKILL_MD):
        print("%s SKILL.md not found" % FAIL)
        return 2

    text = _read_text(SKILL_MD)

    results = [
        ("Test 1  (no agent-recommendation trigger phrasing)", test_no_agent_recommendation_trigger(text)),
        ("Test 2  (required negative trigger statements)",       test_required_negations(text)),
        ("Test 3  (description opt-in preserved)",               test_description_optin_preserved(text)),
        ("Test 4  (execution order: gate before read)",          test_execution_order(text)),
        ("Test 5  (business red-line keywords)",                 test_business_redlines(text)),
        ("Test 6  (protected blocks unchanged vs HEAD)",         test_protected_blocks_unchanged(text)),
        ("Test 7  (broker JSON unchanged vs HEAD)",              test_broker_json_unchanged()),
        ("Test 8  (salary DB unchanged vs HEAD)",                test_salary_db_unchanged()),
        ("Test 9  (references/ zero diff vs HEAD)",              test_references_dir_unchanged()),
    ]

    print("\n" + "=" * 68)
    print("SUMMARY")
    print("=" * 68)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print("  %s %s" % (PASS if ok else FAIL, name))
    print("\n%d/%d tests passed" % (passed, total))

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
