"""学习通扫码登录 (playwright 方案)
1. playwright 打开 i.mooc.chaoxing.com/space/index
2. 截图二维码区域 (登录对话框里的 qr code)
3. 邮件发图
4. playwright 持续监听, 等登录成功（菜单变化 / 跳转）
5. 落盘 storage_state
"""
import sys
import time
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
import config
import notify

LOGIN_PAGE = "https://i.mooc.chaoxing.com/space/index?t=1780816312811"


def log(msg):
    with open('/tmp/chaoxing_qr.log', 'a', encoding='utf-8') as f:
        f.write(str(msg) + '\n')
    print(msg, flush=True)


def main():
    log("[1] 打开登录页")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--no-sandbox", "--single-process", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        # 找二维码图
        qr_locator = page.locator("#quickCode")
        try:
            qr_locator.wait_for(state="visible", timeout=10000)
            log("[2] 找到二维码 #quickCode")
        except Exception as e:
            log(f"[!] 找不到二维码: {e}")
            raise SystemExit("登录页没显示二维码")
        # 截图
        png = qr_locator.screenshot()
        log(f"[3] 截图二维码: {len(png)} bytes")
        # 发邮件
        subject = "[DDL Monitor] 请用学习通 APP 扫码登录"
        html = """
        <h3>请用「学习通」APP 扫描下方二维码完成登录</h3>
        <p><img src="cid:cxqr" width="240" /></p>
        <p>二维码有效期约 150 秒。过期后重新跑 <code>python3 login/chaoxing_qr.py</code>。</p>
        <p>登录态保持 7 天（学习通自动登录机制），到期前可重新扫码续签。</p>
        """
        log(f"[4] 发邮件到 {config.TO_EMAIL}")
        if not notify.send_email(subject, html, inline_images={"cxqr": png}):
            raise SystemExit("邮件发送失败")
        # 等登录
        log("[5] 等待扫码 (最多 150s)...")
        deadline = time.time() + 150
        login_ok = False
        while time.time() < deadline:
            page.wait_for_timeout(3000)
            try:
                # 登录成功的标志: 菜单里"登录"消失 或 URL 跳到 /space/
                menu_items = page.evaluate(
                    "() => Array.from(document.querySelectorAll('.el-menu-item, a, .nav-item')).map(e => (e.innerText||'').trim())"
                )
                body = page.evaluate("() => document.body.innerText")
                if '退出' in body or '退出登录' in body or '个人中心' in body:
                    log(f"[6] 登录成功 (body 含'退出')")
                    login_ok = True
                    break
                if '登录' not in menu_items and '手机号' not in body and '密码' not in body:
                    log(f"[6] 登录成功 (菜单无'登录'且无登录表单)")
                    login_ok = True
                    break
            except Exception as e:
                log(f"[poll err] {e}")
        if not login_ok:
            log("[!] 超时未扫码")
            raise SystemExit(1)
        # 多等 1 秒让 cookie 落定
        page.wait_for_timeout(1500)
        ctx.storage_state(path=str(config.CHAOXING_COOKIE))
        cookies = ctx.cookies()
        log(f"[7] storage_state 已落盘, cookies: {len(cookies)}")
        browser.close()


if __name__ == "__main__":
    main()
