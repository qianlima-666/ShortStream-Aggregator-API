# PyWebIO组件/PyWebIO components
import base64
import binascii
import hashlib
import hmac
import json
import os
import time

import yaml
from pywebio import config as pywebio_config
from pywebio import session
from pywebio.input import PASSWORD, input, input_group, select
from pywebio.output import put_button, put_html, put_markdown, put_row, toast, use_scope

from app.web.views.About import about_pop_window
from app.web.views.Document import api_document_pop_window
from app.web.views.Downloader import downloader_pop_window
from app.web.views.EasterEgg import a
from app.web.views.ParseVideo import parse_video
from app.web.views.Shortcuts import ios_pop_window

# PyWebIO的各个视图/Views of PyWebIO
from app.web.views.ViewsUtils import ViewsUtils

# 读取上级再上级目录的配置文件
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as file:
    _config = yaml.safe_load(file)

pywebio_config(
    theme=_config["Web"]["PyWebIO_Theme"],
    title=_config["Web"]["Tab_Title"],
    description=_config["Web"]["Description"],
    js_file=[
        # 整一个看板娘，二次元浓度++
        _config["Web"]["Live2D_JS"] if _config["Web"]["Live2D_Enable"] else None,
    ],
)


class MainView:
    def __init__(self):
        self.utils = ViewsUtils()

    def require_login(self):
        auth = _config.get("Web", {}).get("Auth", {})
        if not auth or not bool(auth.get("Enabled", False)):
            return
        # 尝试从本地存储读取登录令牌并校验
        try:
            token = session.eval_js('localStorage.getItem("ssa_auth")')
            if token:
                parts = str(token).split(".")
                if len(parts) == 3:
                    u, exp_str, sig = parts
                    secret = str(auth.get("Secret", ""))
                    exp = int(exp_str) if str(exp_str).isdigit() else 0
                    now = int(time.time())
                    expect_sig = hashlib.sha256((secret + u + str(exp_str)).encode("utf-8")).hexdigest()
                    if now < exp and sig == expect_sig and u == str(auth.get("Username", "")):
                        toast(self.utils.t("已登录", "Signed in"))
                        return
                # 令牌无效时清理
                session.eval_js('localStorage.removeItem("ssa_auth")')
        except Exception:
            pass
        while True:
            creds = input_group(
                self.utils.t("🔐 登录", "🔐 Sign In"),
                [
                    input(self.utils.t("用户名", "Username"), name="username", required=True),
                    input(self.utils.t("密码", "Password"), name="password", type=PASSWORD, required=True),
                ],
            )
            ok_user = str(creds.get("username", "")) == str(auth.get("Username", ""))
            pw = str(creds.get("password", ""))
            stored_hash = auth.get("Password_Hash")
            stored_plain = auth.get("Password")
            ok_pwd = False
            if stored_hash:
                ok_pwd = password_verify(pw, stored_hash)
            else:
                ok_pwd = stored_plain is not None and pw == stored_plain
            if ok_user and ok_pwd:
                toast(self.utils.t("登录成功", "Login successful"))
                # 生成并持久化登录令牌（记住登录）
                ttl = int(auth.get("Token_TTL", 86400))
                exp = int(time.time()) + max(60, ttl)
                secret = str(auth.get("Secret", ""))
                token = f"{auth.get('Username', '')}.{exp}.{hashlib.sha256((secret + str(auth.get('Username', '')) + str(exp)).encode('utf-8')).hexdigest()}"
                session.eval_js(f"localStorage.setItem('ssa_auth', {json.dumps(token)})")
                break
            else:
                toast(self.utils.t("账户或密码错误", "Invalid username or password"), color="error")

    # 主界面/Main view
    def main_view(self):
        self.require_login()
        # 左侧导航栏/Left navbar
        with use_scope("main"):
            # 设置favicon/Set favicon
            favicon_url = _config["Web"]["Favicon"]
            session.run_js(f"""
                            $('head').append('<link rel="icon" type="image/png" href="{favicon_url}">')
                            """)
            # 修改footer/Remove footer
            session.run_js("""$('footer').remove()""")
            # 设置不允许referrer/Set no referrer
            session.run_js("""$('head').append('<meta name=referrer content=no-referrer>');""")
            # 设置标题/Set title
            title = self.utils.t("短流聚合 API", "ShortStream Aggregator API")
            put_html(f"""
                    <div align="center">
                    <a href="/" alt="logo" ><img src="{favicon_url}" width="100"/></a>
                    <h1 align="center">{title}</h1>
                    </div>
                    """)
            # 设置导航栏/Navbar
            put_row(
                [
                    put_button(
                        self.utils.t("快捷指令", "iOS Shortcut"),
                        onclick=lambda: ios_pop_window(),
                        link_style=True,
                        small=True,
                    ),
                    put_button(
                        self.utils.t("开放接口", "Open API"),
                        onclick=lambda: api_document_pop_window(),
                        link_style=True,
                        small=True,
                    ),
                    put_button(
                        self.utils.t("下载器", "Downloader"),
                        onclick=lambda: downloader_pop_window(),
                        link_style=True,
                        small=True,
                    ),
                    put_button(
                        self.utils.t("关于", "About"), onclick=lambda: about_pop_window(), link_style=True, small=True
                    ),
                    put_button(
                        self.utils.t("退出登录", "Sign out"), onclick=lambda: self.logout(), link_style=True, small=True
                    ),
                ]
            )

            # 设置功能选择/Function selection
            options = [
                # Index: 0
                self.utils.t("🔍批量解析视频", "🔍Batch Parse Video"),
                # Index: 1
                self.utils.t("🔍解析用户主页视频", "🔍Parse User Homepage Video"),
                # Index: 2
                self.utils.t("🥚小彩蛋", "🥚Easter Egg"),
            ]
            select_options = select(
                self.utils.t("请在这里选择一个你想要的功能吧 ~", "Please select a function you want here ~"),
                required=True,
                options=options,
                help_text=self.utils.t("📎选上面的选项然后点击提交", "📎Select the options above and click Submit"),
            )
            # 根据输入运行不同的函数
            if select_options == options[0]:
                parse_video()
            elif select_options == options[1]:
                put_markdown(self.utils.t("暂未开放，敬请期待~", "Not yet open, please look forward to it~"))
            elif select_options == options[2]:
                a() if _config["Web"]["Easter_Egg"] else put_markdown(self.utils.t("没有小彩蛋哦~", "No Easter Egg~"))

    def logout(self):
        session.run_js("localStorage.removeItem('ssa_auth'); location.reload();")


def _decode_salt(s: str) -> bytes:
    try:
        return binascii.unhexlify(s)
    except (binascii.Error, ValueError):
        return base64.b64decode(s)


def password_verify(password: str, stored: str) -> bool:
    parts = stored.split("$")
    algo = "pbkdf2_sha256"
    if len(parts) == 4:
        algo, iter_str, salt_str, hash_str = parts
    elif len(parts) == 3:
        iter_str, salt_str, hash_str = parts
    else:
        return False
    if "pbkdf2" not in algo:
        return False
    try:
        iters = int(iter_str)
    except ValueError:
        return False
    salt = _decode_salt(salt_str)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    dk_hex = binascii.hexlify(dk).decode()
    return hmac.compare_digest(dk_hex.lower(), hash_str.lower())
