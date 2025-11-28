from pywebio.output import popup, put_link, put_markdown

from app.web.views.ViewsUtils import ViewsUtils

t = ViewsUtils().t


# API文档弹窗/API documentation pop-up
def api_document_pop_window():
    with popup(t("📑API文档", "📑API Document")):
        put_markdown(t("> 介绍", "> Introduction"))
        put_markdown(
            t(
                "你可以利用本项目提供的API接口来获取抖音/TikTok的数据，具体接口文档请参考下方链接。",
                "You can use the API provided by this project to obtain Douyin/TikTok data. For specific API documentation, please refer to the link below.",
            )
        )
        put_markdown(
            t(
                "如果API不可用，请尝试自己部署本项目，然后再配置文件中修改cookie的值。",
                "If the API is not available, please try to deploy this project by yourself, and then modify the value of the cookie in the configuration file.",
            )
        )
        put_link("[API Docs]", "/docs", new_window=True)
        put_markdown("----")
