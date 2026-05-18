# Personal Remote

如果传统控制软件(向日葵 or Todesk)不能用的时候可以用这个：电脑启动 Host，Android 手机打开一个 URL，就能看实时画面并控制鼠标键盘。

默认是安全一点的本地模式：Host 只监听 `127.0.0.1`。如果手机和电脑不在同一个局域网，用 Cloudflare Tunnel / frp 这类反向隧道把本机 `7070` 转成公网 HTTPS URL。

## 功能

- 局域网直连，或者通过公网反向隧道访问
- MJPEG 实时屏幕画面
- 手机直控模式：点击、拖拽、长按右键、双指滚动
- 触控板模式：相对移动鼠标
- 发送文字、Esc、Enter、右键
- 每次连接需要本机密码，认证后使用有过期时间的临时 token
- 默认强随机密码、登录失败限流、本机监听，降低公网误暴露风险

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

如果需要公网访问，额外安装 `cloudflared`，确认命令可用：

```bash
cloudflared --version
```

## 一键命令

已提供 `remote` 命令。它会自动启动 Host、启动 Cloudflare 临时隧道，并打印公网 URL 和本次密码：

```bash
remote
```

关闭后台 Host 和隧道：

```bash
remote close
```

查看当前状态：

```bash
remote status
```

查看日志：

```bash
remote logs
```

## 公网隧道模式

第一个终端启动 Host：

```bash
python3 host/server.py --port 7070
```

终端会显示类似：

```text
Personal Remote Host
Bind:      127.0.0.1:7070
Local URL: http://127.0.0.1:7070
Password:  4NqYxZrXx2...随机密码...
Token TTL: 43200s
Tunnel:    cloudflared tunnel --url http://127.0.0.1:7070
```

第二个终端启动 Cloudflare 临时隧道：

```bash
cloudflared tunnel --url http://127.0.0.1:7070
```

`cloudflared` 会输出一个 `https://xxxx.trycloudflare.com` 地址。Android 手机关闭 Wi-Fi 后也可以打开这个 HTTPS 地址，输入 Host 终端里显示的密码连接。

用完后，在两个终端都按 `Ctrl+C` 关闭。

### 更安全的长期公网模式

临时 `trycloudflare.com` 地址适合短时间应急。长期使用建议：

- 使用自己的域名创建 Cloudflare Named Tunnel
- 给这个域名开启 Cloudflare Access，只允许自己的邮箱或账号访问
- Host 继续保持默认 `--bind 127.0.0.1`
- 不要在路由器上直接开放 `7070` 端口

## 局域网模式

如果手机和电脑在同一个局域网，才需要让 Host 监听局域网地址：

```bash
python3 host/server.py --bind 0.0.0.0 --port 7070
```

终端会显示 `LAN URL`，手机打开这个局域网 URL，输入密码连接。

## 常用参数

```bash
python3 host/server.py \
  --bind 127.0.0.1 \
  --password "换成强密码" \
  --port 7070 \
  --token-ttl 43200 \
  --fps 15 \
  --quality 75 \
  --max-width 1280
```

`--max-width` 控制传输画面的最大宽度，数值越大越清晰，也越吃带宽。`--fps` 越高越流畅，也越吃 CPU。`--token-ttl` 是登录 token 有效期，默认 12 小时。

## 注意

- 公网模式优先用 Cloudflare Tunnel + Access，或者使用 Tailscale / ZeroTier / WireGuard 进入同一个私有网络。
- 不要把 `--bind 0.0.0.0` 和路由器端口转发一起长期暴露在公网。
- 如果局域网模式连不上，检查电脑防火墙是否允许 `7070` 端口。
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
