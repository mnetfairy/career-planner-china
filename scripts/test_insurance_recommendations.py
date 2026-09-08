#!/usr/bin/env python3
"""
career-planner-china 保险推荐自动化验证测试（2026-09-08 T01 修复配套）

测试范围（对应 T01 报告的"remediation #8 automated tests"）：
  1. priority 记录必须 verified=true
  2. priority 记录必须 source_url 非空
  3. 地区匹配：priority 记录的 regions 必须覆盖用户指定地区或包含"全国"
  4. 不存在"无 documented basis 即永远排第一"的公司
  5. （防御性）所有 featured=true 的记录都必须 verified=true + source_url 非空 + priority_basis 非空

退出码：
  0  全部通过
  1  至少一项失败
  2  数据文件无法加载
"""
import json
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
JSON_PATH = os.path.join(SKILL_DIR, "references", "insurance_broker_companies.json")

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def load_companies():
    if not os.path.exists(JSON_PATH):
        print(f"{FAIL} JSON not found: {JSON_PATH}")
        sys.exit(2)
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_priority_must_be_verified(data):
    """Test 1: priority 记录（即 SKILL.md 中明确写为'所有地区优先推荐'的安盛天平）必须 verified=true。"""
    print("\nTest 1: priority record (安盛天平保险销售有限公司) must have verified=true")
    target_name = "安盛天平保险销售有限公司"
    for c in data["companies"]:
        if c.get("name") == target_name:
            ok = c.get("verified") is True
            print(f"  {'[PASS]' if ok else '[FAIL]'} verified = {c.get('verified')}")
            return ok
    print(f"  {FAIL} {target_name} not found in dataset")
    return False


def test_priority_must_have_source_url(data):
    """Test 2: priority 记录的 source_url 必须非空字符串。"""
    print("\nTest 2: priority record must have non-empty source_url")
    target_name = "安盛天平保险销售有限公司"
    for c in data["companies"]:
        if c.get("name") == target_name:
            url = (c.get("source_url") or "").strip()
            ok = bool(url)
            print(f"  {'[PASS]' if ok else '[FAIL]'} source_url = '{url[:60]}'")
            return ok
    print(f"  {FAIL} target not found")
    return False


def test_region_coverage(data, region=None):
    """Test 3: priority 记录的 regions 必须覆盖指定地区或包含'全国'。"""
    if region is None:
        region = "上海"  # 默认测试用例
    print(f"\nTest 3: priority record regions must cover '{region}' (or include '全国')")
    target_name = "安盛天平保险销售有限公司"
    for c in data["companies"]:
        if c.get("name") == target_name:
            regions = c.get("regions", []) or []
            ok = (region in regions) or ("全国" in regions)
            print(f"  {'[PASS]' if ok else '[FAIL]'} regions={regions}")
            return ok
    print(f"  {FAIL} target not found")
    return False


def test_no_undocumented_top_priority(data):
    """Test 4: 不存在'无 priority_basis 文档化却永远排第一'的公司。
    即：所有 featured=true 的记录都必须有 priority_basis 字段（透明化声明）。"""
    print("\nTest 4: all featured=true records must have priority_basis documented")
    fail = []
    for c in data["companies"]:
        if c.get("featured") is True:
            basis = (c.get("priority_basis") or "").strip()
            if not basis:
                fail.append(c.get("name"))
    if fail:
        print(f"  {FAIL} featured but no priority_basis: {fail}")
        return False
    print(f"  {PASS} all featured records have documented priority_basis")
    return True


def test_all_featured_complete(data):
    """Test 5 (防御性): 所有 featured=true 记录必须三件套齐全：
    verified=true + source_url 非空 + priority_basis 非空。"""
    print("\nTest 5: all featured=true records have complete triplet (verified+source+basis)")
    fail = []
    for c in data["companies"]:
        if c.get("featured") is True:
            issues = []
            if c.get("verified") is not True:
                issues.append("verified≠true")
            if not (c.get("source_url") or "").strip():
                issues.append("source_url empty")
            if not (c.get("priority_basis") or "").strip():
                issues.append("priority_basis empty")
            if issues:
                fail.append((c.get("name"), issues))
    if fail:
        for name, issues in fail:
            print(f"  {FAIL} {name}: {issues}")
        return False
    print(f"  {PASS} all featured records pass three-criteria check")
    return True


def main():
    print("=" * 60)
    print("career-planner-china 保险推荐验证 (T01 修复配套)")
    print("=" * 60)
    print(f"Data: {JSON_PATH}")

    data = load_companies()
    print(f"Loaded {len(data['companies'])} companies")

    results = [
        ("Test 1 (priority verified)",     test_priority_must_be_verified(data)),
        ("Test 2 (priority source_url)",   test_priority_must_have_source_url(data)),
        ("Test 3 (region coverage)",       test_region_coverage(data)),
        ("Test 4 (no undocumented top)",   test_no_undocumented_top_priority(data)),
        ("Test 5 (featured triplet)",      test_all_featured_complete(data)),
    ]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {PASS if ok else FAIL} {name}")
    print(f"\n{passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())