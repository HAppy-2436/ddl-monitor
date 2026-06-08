"""mynereus 编程帮账号密码登录"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
import config

LOGIN_PAGE = "http://www.mynereus.com/#/"


def log(msg):
    with open('/tmp/mynereus_login.log', 'a', encoding='utf-8') as f:
        f.write(str(msg) + '\n')
    print(msg, flush=True)


def main():
    if not config.MYNEREUS_USERNAME or not config.MYNEREUS_PASSWORD:
        raise SystemExit("MYNEREUS_USERNAME / MYNEREUS_PASSWORD 未配置")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--single-process", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        ctx = browser.new_context()
        page = ctx.new_page()
        log("[1] browser 启动")
        page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        log("[2] 页面加载完成")
        # 默认登录对话框已显示
        dialog = page.locator(".el-dialog").first
        try:
            dialog.wait_for(state="visible", timeout=5000)
            log("[3] 找到登录对话框")
        except Exception as e:
            log(f"[3] 默认没找到: {e}")
            raise SystemExit("找不到登录对话框")
        inputs = dialog.locator("input")
        n = inputs.count()
        log(f"[4] inputs count: {n}")
        if n < 2:
            raise SystemExit("input 数量异常")
        inputs.nth(0).fill(config.MYNEREUS_USERNAME)
        inputs.nth(1).fill(config.MYNEREUS_PASSWORD)
        log("[5] 已填表, 点登录按钮")
        dialog.locator("button.el-button--primary").first.click()
        page.wait_for_timeout(5000)
        log("[6] 等待结束")
        cookies = ctx.cookies()
        log(f"[7] cookies count: {len(cookies)}")
        for c in cookies:
            log(f"  - {c.get('name')}={c.get('value','')[:30]} domain={c.get('domain')}")
        # 登录成功标志: 登录 dialog 不再可见 (顶层菜单不会因登录改变, 不能用它判断)
        try:
            dialog_still_visible = dialog.is_visible()
        except Exception:
            dialog_still_visible = True  # 出错时保守视为未消失
        # 兜底: 检查页面里是否出现 el-icon-user (登录后的用户头像)
        has_user_icon = page.evaluate('() => !!document.querySelector(".el-icon-user")')
        login_ok = (not dialog_still_visible) and has_user_icon
        log(f"[8] dialog 仍可见: {dialog_still_visible}, 有 el-icon-user: {has_user_icon}")
        log(f"[9] login_ok: {login_ok}")
        if not login_ok:
            raise SystemExit("登录未成功 (dialog 仍可见或缺用户头像)")
        ctx.storage_state(path=str(config.MYNEREUS_COOKIE))
        log(f"[10] storage_state 落盘")
        browser.close()
    log("[11] DONE")


if __name__ == "__main__":
    main()
