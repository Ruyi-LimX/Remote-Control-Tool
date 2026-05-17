# Personal Remote

一个给自己用的局域网远程控制原型：电脑启动 Host，Android 手机打开电脑 IP，就能看实时画面并控制鼠标键盘。

## 功能

- 手动输入电脑 IP 访问，不需要登录、扫码、云服务
- MJPEG 实时屏幕画面
- 手机直控模式：点击、拖拽、长按右键、双指滚动
- 触控板模式：相对移动鼠标
- 发送文字、Esc、Enter、右键
- 每次连接需要本机密码，认证后使用临时 token

## 安装

```bash
cd /home/limx/Desktop/GreatWork/remote
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果 PyPI 下载慢，可以用镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 启动电脑端

```bash
python3 host/server.py --password 123456 --port 7070
```

终端会显示类似：

```text
URL:      http://192.168.1.20:7070
Password: 123456
```

然后在 Android 手机浏览器打开这个 URL，输入密码连接。

## 常用参数

```bash
python3 host/server.py \
  --password 123456 \
  --port 7070 \
  --fps 15 \
  --quality 75 \
  --max-width 1280
```

`--max-width` 控制传输画面的最大宽度，数值越大越清晰，也越吃带宽。`--fps` 越高越流畅，也越吃 CPU。

## 注意

- 手机和电脑需要在同一个局域网，或者通过 Tailscale / ZeroTier / WireGuard 进入同一个私有网络。
- 如果连不上，检查电脑防火墙是否允许 `7070` 端口。
- Linux Wayland 桌面会限制这种简单原型的截图和模拟输入。如果手机端看到黑屏提示，退出当前桌面会话，在登录界面点齿轮，选择 `Ubuntu on Xorg` 后再启动 Host。
- 如果登录界面没有齿轮选项，可以强制 GDM 使用 Xorg：

```bash
sudo cp /etc/gdm3/custom.conf /etc/gdm3/custom.conf.bak.$(date +%Y%m%d-%H%M%S)
sudo sed -i 's/^#WaylandEnable=false/WaylandEnable=false/' /etc/gdm3/custom.conf
grep -q '^WaylandEnable=false' /etc/gdm3/custom.conf || sudo sed -i '/^\\[daemon\\]/a WaylandEnable=false' /etc/gdm3/custom.conf
sudo reboot
```

重启登录后确认：

```bash
echo $XDG_SESSION_TYPE
```

看到 `x11` 后再启动 Host。

如果以后想恢复 Wayland：

```bash
sudo sed -i 's/^WaylandEnable=false/#WaylandEnable=false/' /etc/gdm3/custom.conf
sudo reboot
```

- Windows/macOS 可能需要给终端或 Python 授权辅助功能、屏幕录制或防火墙权限。

## 下一步

- 改成 WebRTC/H.264，降低延迟和带宽
- 加多显示器选择
- 加文件传输和剪贴板同步
- 打包成 Windows/macOS 桌面 Host
- 用 Kotlin 做原生 Android 客户端
