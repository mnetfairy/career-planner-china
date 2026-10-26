#!/usr/bin/env python3
"""
career-planner-china report_generator.py 导出安全性验证（2026-10-26 ClawHub 复审加固，C5）

⚠️ 本测试只使用临时目录，绝不删除 SKILL_DIR/exports 下的任何文件。
   所有导出产物都写入 tempfile.mkdtemp() 建立的临时目录（并通过 AIERA_EXPORT_ROOT
   注入为允许根），shutil.rmtree 只作用于这些临时目录，且使用 ignore_errors=True。
   测试结束时会断言 SKILL_DIR/exports 的内容与运行前完全一致（只读比对）。

断言范围：
  1. 默认输出根是 SKILL_DIR/exports/（不再写 CWD）
  2. 默认根不在 CWD 写文件（旧实现行为）—— 回归守卫
  3. 白名单内路径通过
  4. 越界路径拒绝
  5. 路径穿越（..）拒绝
  6. NUL 字节拒绝
  7. 同名文件不被静默覆盖（独占创建 + collision-resistant 文件名）
  8. 导出文件权限为 0600
  9. --output-dir 本身是 symlink → 拒绝
  10. 父目录链中任一级是 symlink → 拒绝
  11. AIERA_EXPORT_ROOT 可显式扩展允许根
 12. 【新增】允许根（AIERA_EXPORT_ROOT）本身是 symlink → 拒绝，
     且文件**没有**写到 symlink 的目标目录
 13. 【新增】默认 exports/ 目录被替换成 symlink → 拒绝，
     且文件**没有**写到 skill 目录之外
 14. 【回归】用户显式指定普通真实绝对目录 → 仍能成功（防止修过头）

退出码：
  0  全部通过
  1  至少一项失败
"""
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(THIS_DIR)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "report_generator.py")
DEFAULT_EXPORT = os.path.join(SKILL_DIR, "exports")

PASS = "[PASS]"
FAIL = "[FAIL]"

_INITIAL_EXPORT_SNAPSHOT = None


def _snapshot(path):
    """只读快照：返回 {相对路径: (size, mtime_ns)}；目录不存在则返回 None。"""
    if not os.path.isdir(path):
        return None
    snap = {}
    for root, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            snap[os.path.relpath(full, path)] = (st.st_size, st.st_mtime_ns)
    return snap


def _run(script, args, env_extra=None, cwd=None, timeout=30):
    env = os.environ.copy()
    env["LANG"] = "C.UTF-8"
    env.pop("AIERA_EXPORT_ROOT", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["python3", script] + args,
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=cwd or SKILL_DIR,
    )


def _make_fake_skill(tmp_root):
    """在临时目录里复制一份 report_generator.py，构造「假的 skill 根」。

    脚本用 SKILL_DIR = dirname(dirname(__file__)) 推导默认导出根，因此把脚本放到
    <tmp>/fake_skill/scripts/ 下，其默认导出根就变成 <tmp>/fake_skill/exports/
    ——测试可以在临时目录里验证「默认路径」行为，而完全不触碰真实的
    SKILL_DIR/exports。
    """
    fake_skill = os.path.join(tmp_root, "fake_skill")
    fake_scripts = os.path.join(fake_skill, "scripts")
    os.makedirs(fake_scripts, exist_ok=True)
    fake_script = os.path.join(fake_scripts, "report_generator.py")
    shutil.copy2(SCRIPT, fake_script)
    return fake_skill, fake_script


def _module_constants():
    """只读方式读取脚本常量（不执行其 __main__）。"""
    sys.dont_write_bytecode = True  # 避免在 skill 目录里生成 __pycache__
    spec = importlib.util.spec_from_file_location("_rg_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_root_is_skill_exports():
    """Test 1: 默认输出根是 SKILL_DIR/exports/，不是 CWD。"""
    print("\nTest 1: default export root is SKILL_DIR/exports/ (not CWD)")
    try:
        mod = _module_constants()
    except Exception as e:  # noqa: BLE001
        print(f"  {FAIL} cannot import module: {e}")
        return False
    default_root = getattr(mod, "DEFAULT_EXPORT_ROOT", None)
    if not default_root or os.path.realpath(default_root) != os.path.realpath(DEFAULT_EXPORT):
        print(f"  {FAIL} DEFAULT_EXPORT_ROOT={default_root} != {DEFAULT_EXPORT}")
        return False
    print(f"  [PASS] DEFAULT_EXPORT_ROOT == {DEFAULT_EXPORT} (read-only check)")
    return True


def test_does_not_write_to_cwd():
    """Test 2: 在临时 CWD 里运行脚本，不应把报告写到 CWD（旧实现行为）。"""
    print("\nTest 2: script must NOT write the report into the current working directory")
    with tempfile.TemporaryDirectory() as tmp:
        fake_skill, fake_script = _make_fake_skill(tmp)
        cwd_dir = os.path.join(tmp, "cwd_probe")
        os.makedirs(cwd_dir, exist_ok=True)
        data = '{"nickname":"cwd-test"}'
        r = _run(fake_script, ["--data", data], cwd=cwd_dir)
        if r.returncode != 0:
            print(f"  {FAIL} exit={r.returncode}: {r.stderr[:200]}")
            return False
        leaked = [f for f in os.listdir(cwd_dir) if f.endswith(".md")]
        if leaked:
            print(f"  {FAIL} report leaked into CWD: {leaked}")
            return False
        fake_export = os.path.join(fake_skill, "exports")
        produced = sorted(os.listdir(fake_export)) if os.path.isdir(fake_export) else []
        if not produced:
            print(f"  {FAIL} nothing written to the skill export dir either")
            return False
        print(f"  {PASS} CWD clean; output went to skill export dir: {produced[0]}")
        return True


def test_within_allowed_root():
    """Test 3: 白名单内路径通过。"""
    print("\nTest 3: explicit --output-dir inside the allowed root succeeds")
    with tempfile.TemporaryDirectory() as tmp:
        fake_skill, fake_script = _make_fake_skill(tmp)
        out_dir = os.path.join(fake_skill, "exports")
        data = '{"nickname":"allowed"}'
        r = _run(fake_script, ["--data", data, "--output-dir", out_dir])
        if r.returncode != 0:
            print(f"  {FAIL} exit={r.returncode}: {r.stderr[:200]}")
            return False
        print(f"  {PASS} accepted, output: {r.stdout.strip()}")
        return True


def test_outside_allowed_root():
    """Test 4: 越界路径拒绝。"""
    print("\nTest 4: --output-dir outside allowed roots should be REJECTED")
    with tempfile.TemporaryDirectory() as tmp_out, tempfile.TemporaryDirectory() as tmp_home:
        fake_skill, fake_script = _make_fake_skill(tmp_home)
        data = '{"nickname":"outside"}'
        r = _run(fake_script, ["--data", data, "--output-dir", os.path.realpath(tmp_out)])
        if r.returncode == 0:
            print(f"  {FAIL} out-of-root path was ACCEPTED; stdout={r.stdout[:200]}")
            return False
        print(f"  {PASS} rejected (exit={r.returncode}): {r.stderr.strip()[:120]}")
        return True


def test_path_traversal():
    """Test 5: 路径穿越（..）拒绝。"""
    print("\nTest 5: path traversal '../..' should be REJECTED")
    with tempfile.TemporaryDirectory() as tmp:
        fake_skill, fake_script = _make_fake_skill(tmp)
        data = '{"nickname":"traversal"}'
        r = _run(fake_script, ["--data", data, "--output-dir", "./exports/../../etc"])
        if r.returncode == 0:
            print(f"  {FAIL} traversal path was ACCEPTED")
            return False
        print(f"  {PASS} traversal rejected (exit={r.returncode}): {r.stderr.strip()[:120]}")
        return True


def test_nul_byte():
    """Test 6: NUL 字节拒绝。

    注意：NUL 字节无法通过 subprocess 的 argv 传递（CPython 在 exec 阶段就抛
    ValueError: embedded null byte），因此本用例直接调用模块内的
    _validate_output_dir 校验函数来断言拒绝行为。
    """
    print("\nTest 6: NUL byte in --output-dir should be REJECTED")
    try:
        mod = _module_constants()
    except Exception as e:  # noqa: BLE001
        print(f"  {FAIL} cannot import module: {e}")
        return False
    allowed = mod._load_allowed_roots()
    try:
        mod._validate_output_dir(os.path.join(tempfile.gettempdir(), "a\x00b"), allowed)
    except ValueError as e:
        if "NUL" not in str(e):
            print(f"  {FAIL} rejected with unexpected message: {e}")
            return False
        print(f"  [PASS] NUL byte rejected: {e}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  {FAIL} unexpected exception type: {type(e).__name__}: {e}")
        return False
    print(f"  {FAIL} NUL-byte path was ACCEPTED")
    return False


def test_no_overwrite():
    """Test 7: 连续两次导出生成不同文件，不静默覆盖（旧实现会被覆盖）。"""
    print("\nTest 7: two consecutive exports must NOT overwrite each other")
    with tempfile.TemporaryDirectory() as tmp:
        fake_skill, fake_script = _make_fake_skill(tmp)
        out_dir = os.path.join(fake_skill, "exports")
        data = '{"nickname":"overwrite"}'
        r1 = _run(fake_script, ["--data", data, "--output-dir", out_dir])
        time.sleep(1)
        r2 = _run(fake_script, ["--data", data, "--output-dir", out_dir])
        files = sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []
        if r1.returncode != 0 or r2.returncode != 0:
            print(f"  {FAIL} one run failed: r1={r1.returncode} r2={r2.returncode}")
            return False
        if len(files) < 2:
            print(f"  {FAIL} only {len(files)} file(s) created; expected >=2: {files}")
            return False
        print(f"  {PASS} {len(files)} distinct files created: {files}")
        return True


def test_file_permission_0600():
    """Test 8: 导出文件权限为 0600。"""
    print("\nTest 8: exported report file permission should be 0600")
    with tempfile.TemporaryDirectory() as tmp:
        fake_skill, fake_script = _make_fake_skill(tmp)
        out_dir = os.path.join(fake_skill, "exports")
        data = '{"nickname":"perm"}'
        r = _run(fake_script, ["--data", data, "--output-dir", out_dir])
        if r.returncode != 0:
            print(f"  {FAIL} exit={r.returncode}: {r.stderr[:200]}")
            return False
        files = [f for f in os.listdir(out_dir) if f.endswith(".md")]
        if not files:
            print(f"  {FAIL} no report file produced")
            return False
        mode = stat.S_IMODE(os.stat(os.path.join(out_dir, files[0])).st_mode)
        if mode != 0o600:
            print(f"  {FAIL} file mode is {oct(mode)}, expected 0o600")
            return False
        print(f"  {PASS} file mode = {oct(mode)}")
        return True


def test_output_dir_is_symlink():
    """Test 9: --output-dir 本身是 symlink → 拒绝。"""
    print("\nTest 9: --output-dir is a symlink -> must be REJECTED")
    with tempfile.TemporaryDirectory() as tmp:
        real_target = os.path.join(tmp, "real_out")
        os.makedirs(real_target, exist_ok=True)
        link = os.path.join(tmp, "link_out")
        try:
            os.symlink(real_target, link)
        except (OSError, NotImplementedError) as e:
            print(f"  {FAIL} cannot create symlink on this platform: {e}")
            return False
        fake_skill, fake_script = _make_fake_skill(tmp)
        env_extra = {"AIERA_EXPORT_ROOT": os.path.realpath(tmp)}
        data = '{"nickname":"symlink"}'
        r = _run(fake_script, ["--data", data, "--output-dir", link], env_extra=env_extra)
        if r.returncode == 0:
            print(f"  {FAIL} symlink output-dir was ACCEPTED; stdout={r.stdout[:200]}")
            return False
        if "symlink" not in r.stderr.lower():
            print(f"  {FAIL} rejected but not by the symlink guard: {r.stderr.strip()[:200]}")
            return False
        print(f"  {PASS} symlink output-dir rejected (exit={r.returncode}): {r.stderr.strip()[:120]}")
        return True


def test_parent_chain_symlink():
    """Test 10: 父目录链中任一级是 symlink → 拒绝。"""
    print("\nTest 10: a symlink anywhere in the parent chain -> must be REJECTED")
    with tempfile.TemporaryDirectory() as tmp:
        real_sub = os.path.join(tmp, "real_sub")
        os.makedirs(real_sub, exist_ok=True)
        link_sub = os.path.join(tmp, "link_sub")
        try:
            os.symlink(real_sub, link_sub)
        except (OSError, NotImplementedError) as e:
            print(f"  {FAIL} cannot create symlink on this platform: {e}")
            return False
        target = os.path.join(link_sub, "sub_out")
        fake_skill, fake_script = _make_fake_skill(tmp)
        env_extra = {"AIERA_EXPORT_ROOT": os.path.realpath(tmp)}
        data = '{"nickname":"parent-symlink"}'
        r = _run(fake_script, ["--data", data, "--output-dir", target], env_extra=env_extra)
        if r.returncode == 0:
            print(f"  {FAIL} parent-chain symlink was ACCEPTED; stdout={r.stdout[:200]}")
            return False
        if "symlink" not in r.stderr.lower():
            print(f"  {FAIL} rejected but not by the symlink guard: {r.stderr.strip()[:200]}")
            return False
        print(f"  {PASS} parent-chain symlink rejected (exit={r.returncode}): {r.stderr.strip()[:120]}")
        return True


def test_env_var_override():
    """Test 11: AIERA_EXPORT_ROOT 可显式扩展允许根。"""
    print("\nTest 11: AIERA_EXPORT_ROOT env var should extend allowed roots")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_real = os.path.realpath(tmp)
        fake_skill, fake_script = _make_fake_skill(tmp)
        env_extra = {"AIERA_EXPORT_ROOT": tmp_real}
        data = '{"nickname":"env-var"}'
        r = _run(fake_script, ["--data", data, "--output-dir", tmp_real], env_extra=env_extra)
        if r.returncode != 0:
            print(f"  {FAIL} env var override not honored: exit={r.returncode} stderr={r.stderr[:200]}")
            return False
        files = [f for f in os.listdir(tmp_real) if f.startswith("职业规划报告_")]
        if not files:
            print(f"  {FAIL} no file created in env-var directory: {os.listdir(tmp_real)}")
            return False
        print(f"  {PASS} env var honored; file: {files[0]}")
        return True


def test_allowed_root_is_symlink():
    """Test 12: 允许根（AIERA_EXPORT_ROOT）本身是 symlink → 拒绝。

    2026-10-27 加固（ClawHub 第二轮 P0）：旧实现把允许根的「字面路径」当作
    豁免锚点，允许根本身是 symlink 时整条链的 symlink 检查被跳过，文件会写到
    symlink 目标目录（允许根之外）。本用例断言：
      a) 命令被拒绝（exit != 0）
      b) symlink 的目标目录里**没有**产生任何报告文件
    """
    print("\nTest 12: allowed root itself is a symlink -> must be REJECTED (no write to target)")
    with tempfile.TemporaryDirectory() as tmp:
        real_root = os.path.join(tmp, "real_root")
        os.makedirs(real_root, exist_ok=True)
        root_link = os.path.join(tmp, "root_link")
        try:
            os.symlink(real_root, root_link)
        except (OSError, NotImplementedError) as e:
            print(f"  {FAIL} cannot create symlink on this platform: {e}")
            return False
        out_dir = os.path.join(root_link, "sub")
        os.makedirs(out_dir, exist_ok=True)
        fake_skill, fake_script = _make_fake_skill(tmp)
        env_extra = {"AIERA_EXPORT_ROOT": root_link}
        data = '{"nickname":"allowed-root-symlink"}'
        r = _run(fake_script, ["--data", data, "--output-dir", out_dir], env_extra=env_extra)
        if r.returncode == 0:
            print(f"  {FAIL} symlink allowed root was ACCEPTED; stdout={r.stdout[:200]}")
            return False
        leaked = []
        for root, _dirs, files in os.walk(real_root):
            for name in files:
                if name.endswith(".md"):
                    leaked.append(os.path.join(root, name))
        if leaked:
            print(f"  {FAIL} report was written to the symlink target dir: {leaked}")
            return False
        print(f"  {PASS} symlink allowed root rejected (exit={r.returncode}); "
              f"nothing written to target dir")
        return True


def test_default_exports_is_symlink():
    """Test 13: 默认 exports/ 目录被替换成 symlink → 拒绝。

    2026-10-27 加固（ClawHub 第二轮 P0）：默认导出根（SKILL_DIR/exports/）
    走与 AIERA_EXPORT_ROOT 完全相同的检查路径——是 symlink 就不可用于授权。
    本用例在**临时目录**里造一个假 skill 根（脚本副本），把它的 exports/ 换成
    symlink，断言命令被拒绝，且文件没有写到 skill 目录之外。
    """
    print("\nTest 13: default exports/ dir is a symlink -> must be REJECTED (no write outside skill)")
    with tempfile.TemporaryDirectory() as tmp:
        fake_skill, fake_script = _make_fake_skill(tmp)
        real_exports = os.path.join(tmp, "real_exports")
        os.makedirs(real_exports, exist_ok=True)
        exports_link = os.path.join(fake_skill, "exports")
        try:
            os.symlink(real_exports, exports_link)
        except (OSError, NotImplementedError) as e:
            print(f"  {FAIL} cannot create symlink on this platform: {e}")
            return False
        data = '{"nickname":"default-exports-symlink"}'
        r = _run(fake_script, ["--data", data])
        if r.returncode == 0:
            print(f"  {FAIL} symlinked default exports was ACCEPTED; stdout={r.stdout[:200]}")
            return False
        leaked = [f for f in os.listdir(real_exports) if f.endswith(".md")]
        if leaked:
            print(f"  {FAIL} report was written outside the skill dir: {leaked}")
            return False
        print(f"  {PASS} symlinked default exports rejected (exit={r.returncode}); "
              f"nothing written outside the skill dir")
        return True


def test_plain_absolute_dir_still_works():
    """Test 14 [回归]: 用户显式指定普通真实绝对目录 → 仍能成功。

    防止修复过头：收窄豁免范围之后，正常的显式目录用法不能被误拒。
    """
    print("\nTest 14 [regression]: explicit plain real absolute dir should still SUCCEED")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_real = os.path.realpath(tmp)
        fake_skill, fake_script = _make_fake_skill(tmp)
        env_extra = {"AIERA_EXPORT_ROOT": tmp_real}
        data = '{"nickname":"plain-dir-regression"}'
        r = _run(fake_script, ["--data", data, "--output-dir", tmp_real], env_extra=env_extra)
        if r.returncode != 0:
            print(f"  {FAIL} plain absolute dir was REJECTED; exit={r.returncode} "
                  f"stderr={r.stderr[:200]}")
            return False
        files = [f for f in os.listdir(tmp_real) if f.startswith("职业规划报告_")]
        if not files:
            print(f"  {FAIL} no report produced in the plain dir: {os.listdir(tmp_real)}")
            return False
        print(f"  {PASS} plain absolute dir accepted; file: {files[0]}")
        return True


def main():
    global _INITIAL_EXPORT_SNAPSHOT
    _INITIAL_EXPORT_SNAPSHOT = _snapshot(DEFAULT_EXPORT)

    print("=" * 60)
    print("career-planner-china report_generator 导出安全性验证 (2026-10-26 加固)")
    print("=" * 60)
    print(f"Script: {SCRIPT}")
    print(f"注意：只使用临时目录，绝不删除 {DEFAULT_EXPORT} 下的任何文件")

    results = [
        ("Test 1  (default root = SKILL/exports)",   test_default_root_is_skill_exports()),
        ("Test 2  (no write into CWD)",             test_does_not_write_to_cwd()),
        ("Test 3  (within allowed root)",           test_within_allowed_root()),
        ("Test 4  (outside allowed root)",          test_outside_allowed_root()),
        ("Test 5  (path traversal rejected)",       test_path_traversal()),
        ("Test 6  (NUL byte rejected)",             test_nul_byte()),
        ("Test 7  (no overwrite)",                  test_no_overwrite()),
        ("Test 8  (file mode 0600)",                test_file_permission_0600()),
        ("Test 9  (output-dir is symlink)",         test_output_dir_is_symlink()),
        ("Test 10 (parent chain symlink)",          test_parent_chain_symlink()),
        ("Test 11 (env var override)",              test_env_var_override()),
        ("Test 12 (allowed root is symlink)",       test_allowed_root_is_symlink()),
        ("Test 13 (default exports symlink)",       test_default_exports_is_symlink()),
        ("Test 14 (plain abs dir regression)",      test_plain_absolute_dir_still_works()),
    ]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {PASS if ok else FAIL} {name}")
    print(f"\n{passed}/{total} tests passed")

    final_snapshot = _snapshot(DEFAULT_EXPORT)
    unchanged = final_snapshot == _INITIAL_EXPORT_SNAPSHOT
    print(f"\n  {PASS if unchanged else FAIL} real exports dir unchanged: "
          f"{DEFAULT_EXPORT} (before={_INITIAL_EXPORT_SNAPSHOT}, after={final_snapshot})")

    return 0 if (passed == total and unchanged) else 1


if __name__ == "__main__":
    sys.exit(main())
