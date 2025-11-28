import os
import shutil
import uvicorn


def _ensure_config_examples_copied():
    os.makedirs("config", exist_ok=True)
    for file in os.listdir("config.example"):
        src = os.path.join("config.example", file)
        if not os.path.isfile(src):
            continue
        dst = os.path.join("config", file)
        if not os.path.exists(dst):
            shutil.copy(src, dst)
            print(f"复制 {file} 到 config 文件夹")


if __name__ == "__main__":
    _ensure_config_examples_copied()
    from app.main import Host_IP, Host_Port
    uvicorn.run("app.main:app", host=Host_IP, port=Host_Port, reload=True, log_level="info")
