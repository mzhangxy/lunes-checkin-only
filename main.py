import os
import time
import json
import base64
import requests
import sys
import shutil
import traceback
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions
from nacl import encoding, public

class LunesAuto:
    def __init__(self):
        # 基础配置
        self.cookie_env = os.getenv('LUNES_COOKIE', '')
        self.panel_user = os.getenv('PANEL_USER')
        self.panel_pass = os.getenv('PANEL_PASS')
        
        # TG 通知配置
        self.tg_token = os.getenv('TG_BOT_TOKEN')
        self.tg_chat_id = os.getenv('TG_CHAT_ID')
        
        # GitHub Secret 配置
        self.repo_name = os.getenv("GITHUB_REPOSITORY")
        self.repo_token = os.getenv("REPO_TOKEN")

    def log(self, msg):
        """带时间戳的日志"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        sys.stdout.flush()

    def screenshot(self, page, name):
        """辅助截图函数"""
        try:
            ts = datetime.now().strftime('%H%M%S')
            filename = f"{name}.jpg" # 简化文件名，方便发送
            page.get_screenshot(path=filename, full_page=True)
            self.log(f"📸 Screenshot saved: {filename}")
            return filename
        except Exception as e:
            self.log(f"⚠️ Screenshot failed: {e}")
            return None

    def send_tg(self, message, image_path=None):
        """
        发送 Telegram 通知 (支持图片)
        :param message: 消息文本
        :param image_path: 图片路径 (可选)
        """
        if not self.tg_token or not self.tg_chat_id:
            return
        
        try:
            # 情况1：发送带图片的文字消息
            if image_path and os.path.exists(image_path):
                url = f"https://api.telegram.org/bot{self.tg_token}/sendPhoto"
                with open(image_path, 'rb') as f:
                    # 注意：发送图片时，文字字段是 'caption'
                    payload = {
                        "chat_id": self.tg_chat_id, 
                        "caption": message,
                        "parse_mode": "HTML"
                    }
                    files = {"photo": f}
                    requests.post(url, data=payload, files=files, timeout=20)
                self.log(f"📤 TG Photo sent with caption: {message}")
            
            # 情况2：仅发送文字消息
            else:
                url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
                payload = {
                    "chat_id": self.tg_chat_id, 
                    "text": message,
                    "parse_mode": "HTML"
                }
                requests.post(url, json=payload, timeout=10)
                self.log(f"📤 TG Message sent: {message}")

        except Exception as e:
            self.log(f"⚠️ TG Send failed: {e}")

    def update_secret(self, new_cookies):
        """更新 GitHub Secret"""
        if not self.repo_token or not self.repo_name:
            self.log("⚠️ Missing REPO_TOKEN, skipping Secret update")
            return

        try:
            # new_cookies 已经是 list[dict]
            session_cookie = next((c for c in new_cookies if c['name'] == 'session'), None)
            if session_cookie:
                final_data = [session_cookie]
            else:
                final_data = new_cookies

            final_json = json.dumps(final_data)
            
            if self.cookie_env and final_json == self.cookie_env:
                self.log("ℹ️ Cookie unchanged")
                return

            self.log("🔄 Cookie change detected, updating Secret...")
            
            headers = {"Authorization": f"token {self.repo_token}", "Accept": "application/vnd.github.v3+json"}
            base_url = f"https://api.github.com/repos/{self.repo_name}/actions/secrets"
            
            r = requests.get(f"{base_url}/public-key", headers=headers)
            key_data = r.json()
            public_key = key_data['key']
            key_id = key_data['key_id']

            pk = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
            sealed_box = public.SealedBox(pk)
            encrypted = base64.b64encode(sealed_box.encrypt(final_json.encode("utf-8"))).decode("utf-8")

            data = {"encrypted_value": encrypted, "key_id": key_id}
            requests.put(f"{base_url}/LUNES_COOKIE", headers=headers, json=data)
            self.log("✅ Secret updated successfully")

        except Exception as e:
            self.log(f"⚠️ Secret update failed: {e}")

    def solve_turnstile(self, page):
        """DrissionPage 专用过盾逻辑"""
        self.log("🛡️ [Turnstile] Detecting protection...")
        self.screenshot(page, "debug_turnstile_start")
        
        try:
            if page.ele('css:[name="cf-turnstile-response"]', timeout=2):
                val = page.ele('css:[name="cf-turnstile-response"]').value
                if val:
                    self.log("⚡ [Auto-Pass] Token already exists!")
                    return True

            self.log("🔍 Waiting for Turnstile Iframe (max 20s)...")
            iframe_ele = page.ele('css:iframe[src*="challenges"]', timeout=20)
            
            if not iframe_ele:
                self.log("⚠️ Timeout: Turnstile Iframe not found")
                self.screenshot(page, "debug_no_turnstile_iframe")
                return False
            
            self.log("✅ Iframe found")
            iframe = page.get_frame(iframe_ele)
            time.sleep(1)

            click_success = False
            try:
                body = iframe.ele('tag:body')
                if not body:
                    self.log("⚠️ Cannot get Iframe Body")
                else:
                    sr = body.shadow_root
                    if sr:
                        self.log("🔓 ShadowRoot entered")
                        cb = sr.ele('css:input[type="checkbox"]') or sr.ele('css:div.main-wrapper')
                        if cb:
                            self.log("🖱️ [Pierce] Checkbox found, clicking!")
                            self.screenshot(page, "debug_before_click_sr")
                            cb.click()
                            click_success = True
                        else:
                            self.log("⚠️ Checkbox not found in ShadowRoot")
                    else:
                        self.log("⚠️ ShadowRoot not detected")
            except Exception as e:
                self.log(f"⚠️ Pierce failed: {e}")

            if not click_success:
                self.log("🏹 [Fallback] Clicking coordinates (20, 30)...")
                iframe.click.at(offset_x=20, offset_y=30)

            self.log("⏳ Waiting for verification...")
            for i in range(15):
                time.sleep(1)
                res_ele = page.ele('css:[name="cf-turnstile-response"]')
                if res_ele and res_ele.value:
                    self.log(f"🎉 Verification Success (Token generated, {i+1}s)")
                    return True
                if not page.get_frame('src:challenges.cloudflare.com'):
                    self.log("🎉 Verification Success (Iframe disappeared)")
                    return True
            
            self.log("❌ Verification Timeout")
            self.screenshot(page, "debug_turnstile_timeout")
            return False

        except Exception as e:
            self.log(f"🔥 Turnstile Exception: {e}")
            return False

    def run(self):
        co = ChromiumOptions()
        co.headless(False)
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-gpu')
        co.set_user_data_path("./tmp_browser_data")
        co.auto_port()

        page = ChromiumPage(co)
        
        try:
            self.log("🚀 Starting Automation...")
            
            # 1. Inject Cookie
            if self.cookie_env:
                try:
                    page.set.cookies(json.loads(self.cookie_env))
                    self.log("🍪 Cookie injected")
                except: pass

            # 2. Visit Home
            self.log("🌐 Visiting Lunes Home...")
            page.get("https://betadash.lunes.host/", retry=3, interval=2)
            time.sleep(5)

            # +++ 新增：全局拦截检测 +++
            # 如果页面上出现了 Turnstile 的 iframe，说明被拦截了，优先解盾
            if page.ele('css:iframe[src*="challenges"]', timeout=3):
                self.log("🛡️ Cloudflare verification detected on homepage!")
                self.solve_turnstile(page)
                time.sleep(3) # 解盾后给页面一点加载时间

            # 3. Login Flow
            if "/login" in page.url or page.ele("text:Sign in") or page.ele("text:Continue"):
                self.log("🔒 Entering Login Flow...")
                if not self.panel_user or not self.panel_pass:
                    raise Exception("Missing Credentials")

                self.log("⌨️ Inputting Credentials...")
                page.ele('css:input[name="email"]').input(self.panel_user)
                page.ele('css:input[name="password"]').input(self.panel_pass)
                self.screenshot(page, "login_filled")
                time.sleep(2) 

                self.solve_turnstile(page)

                self.log("🖱️ Clicking Login Button...")
                btn = page.ele('text:Continue to dashboard') or page.ele('text:Sign in') or page.ele('text:Continue')
                
                if btn:
                    self.screenshot(page, "before_login_click")
                    btn.click()
                else:
                    self.log("⚠️ Button not found, trying Enter")
                    page.ele('css:input[name="password"]').press('Enter')
                
                self.log("⏳ Waiting for redirection (20s)...")
                success_jump = False
                for i in range(20):
                    time.sleep(1)
                    if "/login" not in page.url:
                        self.log("🎉 Redirect Success!")
                        success_jump = True
                        break
                    if i % 5 == 0:
                        self.log(f"   ...waiting ({i}s)")
                
                if not success_jump:
                    self.log("❌ Redirect Timeout")
                    page.get_screenshot(path='login_failed_final.jpg', full_page=True)
                    raise Exception("Login Failed")
                
                self.update_secret(page.cookies())

            # 4. Find Server Card
            self.log("🔍 Searching for Server Card...")
            server_card = page.ele('text:Tap to open console', timeout=5)
            
            if not server_card:
                self.log("⚠️ 'Tap to open console' not found, trying 'Active' tag...")
                server_card = page.ele('text:Active')
                
            if not server_card:
                self.log("⚠️ trying server name 'color'...")
                server_card = page.ele('text:color')

            if not server_card:
                self.screenshot(page, "no_server_card_found")
                raise Exception("Cannot find Server Card")
            
            self.log("🖱️ Clicking Server Card...")
            server_card.click()
            time.sleep(5)

            # Click Open Panel
            panel_btn = page.ele('text:Open Panel')
            if panel_btn:
                self.log("🖱️ Clicking Open Panel")
                panel_btn.click()
                time.sleep(8)

            # === Pterodactyl Login ===
            ptero_user_ele = page.ele('css:input[name="username"]') or page.ele('css:input[name="user"]')
            
            if ptero_user_ele:
                self.log("🔒 Pterodactyl Login Detected...")
                ptero_user_ele.input(self.panel_user)
                page.ele('css:input[name="password"]').input(self.panel_pass)
                
                self.log("🖱️ Clicking Pterodactyl Login Button...")
                
                login_btn = page.ele('css:button[type="submit"]')
                if not login_btn:
                    login_btn = page.ele('text:LOGIN') or page.ele('text:Login')
                
                if login_btn:
                    login_btn.click()
                else:
                    self.log("⚠️ Pterodactyl login button not found, simulating Enter key...")
                    page.ele('css:input[name="password"]').press('Enter')

                # +++ 新增：检测并处理弹出的 reCAPTCHA 挑战 +++
                self.log("🔍 Checking for reCAPTCHA challenge popup...")
                # reCAPTCHA 弹窗的 iframe 通常 title 包含 "recaptcha challenge" 或 src 包含 "bframe"
                bframe_ele = page.ele('css:iframe[title*="recaptcha challenge"]', timeout=5) or page.ele('css:iframe[src*="bframe"]', timeout=5)
                
                if bframe_ele:
                    self.log("🛡️ reCAPTCHA Challenge detected! Initiating audio solver...")
                    bframe = page.get_frame(bframe_ele)
                    
                    # 实例化你的音频破解器
                    solver = RecaptchaAudioSolver(page)
                    solver.log_func = self.log # 将 solver 的日志输出重定向到你的主控 log
                    
                    success = solver.solve(bframe)
                    if success:
                        self.log("✅ Audio challenge solved successfully!")
                        time.sleep(3) # 给页面一点时间完成登录跳转
                    else:
                        self.log("❌ Audio challenge failed.")
                        self.screenshot(page, "audio_solve_failed")
                else:
                    self.log("✅ No secondary reCAPTCHA challenge detected.")

                time.sleep(8)
                
                srv_inner = page.ele('css:a[href*="/server/"]')
                if srv_inner: 
                    self.log("🖱️ Clicking inner server link...")
                    srv_inner.click()
                    time.sleep(5)

            # Restart Logic
            self.log("🔄 Looking for Restart Button...")
            self.screenshot(page, "console_page")
            
            if "Create Server" in page.html and "Start" not in page.html:
                 self.log("❌ Wrong page detected (Create Server).")
                 return

            restart = page.ele('text:Restart', timeout=10) or page.ele('text:Start')
            
            if restart:
                restart.click()
                self.log("✅ Click Success")
                # 保存截图并发送带图通知
                img_path = self.screenshot(page, "success")
                self.send_tg("✅ <b>Lunes 续期成功</b>\n已执行 Restart 操作", img_path)
            else:
                self.log("⚠️ Restart Button Not Found")
                # 失败也发图
                img_path = self.screenshot(page, "no_restart_btn")
                self.send_tg("⚠️ <b>Lunes 警告</b>\n登录成功但未找到重启按钮", img_path)

        except Exception as e:
            self.log(f"❌ Error: {e}")
            traceback.print_exc()
            # 崩溃时发图
            img_path = self.screenshot(page, "crash_error")
            self.send_tg(f"❌ <b>Lunes 运行出错</b>\n错误信息: {str(e)}", img_path)
        finally:
            page.quit()
            if os.path.exists("./tmp_browser_data"):
                try: shutil.rmtree("./tmp_browser_data")
                except: pass

if __name__ == "__main__":
    bot = LunesAuto()
    bot.run()
