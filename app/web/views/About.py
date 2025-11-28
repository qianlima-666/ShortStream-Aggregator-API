import os
import yaml
from pywebio.output import popup, put_markdown, put_html, put_text
from app.web.views.ViewsUtils import ViewsUtils

t = ViewsUtils().t

# 读取配置文件路径
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'config.yaml')
with open(config_path, 'r', encoding='utf-8') as file:
    _config = yaml.safe_load(file)


def about_pop_window():
    """关于弹窗，显示 Logo、名称与版本信息"""
    with popup(t('更多信息', 'More Information')):
        web = _config['Web']
        api = _config['API']
        favicon_url = web['Favicon']
        app_name_cn = '短流聚合 API'
        app_name_en = 'ShortStream Aggregator API'
        version = api['Version']

        put_html(f"""
                <div align="center">
                  <img src="{favicon_url}" width="100" alt="logo"/>
                  <h3>{t(app_name_cn, app_name_en)}</h3>
                </div>
                """)
        put_text(t(f"名称：{web['Tab_Title']}", f"Name: {web['Tab_Title']}"))
        put_text(t(f"版本：{version}", f"Version: {version}"))
