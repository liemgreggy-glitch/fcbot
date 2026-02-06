# 部署指南 (Deployment Guide)

本文档提供完整的部署指南，包括本地开发、VPS部署、Docker部署等多种方式。

## 📋 部署前准备

### 1. 系统要求
- **操作系统**: Linux / macOS / Windows
- **Python版本**: 3.8 或更高
- **内存**: 至少 512MB
- **存储**: 至少 100MB 可用空间

### 2. 获取 Bot Token

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 命令
3. 按提示设置机器人名称和用户名
4. 复制获得的 Token（格式：`1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`）

### 3. 获取用户 ID（可选）

1. 在 Telegram 中搜索 `@userinfobot`
2. 发送任意消息
3. 机器人会返回你的用户 ID

## 🚀 部署方式

### 方式一：本地开发运行

适合测试和开发环境。

#### 步骤：

```bash
# 1. 克隆仓库
git clone https://github.com/liemgreggy-glitch/fcbot.git
cd fcbot

# 2. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
nano .env  # 编辑填入你的 Bot Token

# 5. 运行机器人
python bot.py
```

#### 停止机器人：
按 `Ctrl+C` 停止运行

### 方式二：VPS 后台运行（推荐）

适合生产环境，使用 `screen` 或 `systemd` 保持运行。

#### 选项 A: 使用 screen

```bash
# 1. 安装 screen（如果没有）
sudo apt-get install screen  # Ubuntu/Debian
sudo yum install screen       # CentOS/RHEL

# 2. 创建新会话
screen -S fcbot

# 3. 在 screen 中运行机器人
cd /path/to/fcbot
python bot.py

# 4. 分离会话（保持后台运行）
# 按 Ctrl+A，然后按 D

# 5. 重新连接会话
screen -r fcbot

# 6. 查看所有会话
screen -ls

# 7. 关闭会话
# 在会话中输入 exit 或按 Ctrl+D
```

#### 选项 B: 使用 systemd（推荐用于生产）

```bash
# 1. 创建 systemd 服务文件
sudo nano /etc/systemd/system/fcbot.service
```

填入以下内容：

```ini
[Unit]
Description=Macau Lottery Telegram Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/fcbot
Environment="PATH=/path/to/fcbot/venv/bin"
ExecStart=/path/to/fcbot/venv/bin/python /path/to/fcbot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**注意**：替换以下内容：
- `YOUR_USERNAME` - 你的Linux用户名
- `/path/to/fcbot` - bot.py 所在的完整路径

```bash
# 2. 重载 systemd
sudo systemctl daemon-reload

# 3. 启动服务
sudo systemctl start fcbot

# 4. 设置开机自启
sudo systemctl enable fcbot

# 5. 查看状态
sudo systemctl status fcbot

# 6. 查看日志
sudo journalctl -u fcbot -f

# 7. 停止服务
sudo systemctl stop fcbot

# 8. 重启服务
sudo systemctl restart fcbot
```

### 方式三：Docker 部署

适合容器化环境。

#### 步骤：

1. **创建 Dockerfile**

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY bot.py .

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 运行
CMD ["python", "bot.py"]
```

2. **创建 docker-compose.yml**

```yaml
version: '3.8'

services:
  fcbot:
    build: .
    container_name: fcbot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./lottery.db:/app/lottery.db
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Shanghai
```

3. **构建和运行**

```bash
# 构建镜像
docker-compose build

# 启动容器
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止容器
docker-compose down

# 重启容器
docker-compose restart
```

### 方式四：云服务器部署

#### AWS EC2

```bash
# 1. 连接到 EC2 实例
ssh -i your-key.pem ubuntu@your-ec2-ip

# 2. 更新系统
sudo apt update && sudo apt upgrade -y

# 3. 安装 Python 和 Git
sudo apt install python3 python3-pip git -y

# 4. 克隆仓库
git clone https://github.com/liemgreggy-glitch/fcbot.git
cd fcbot

# 5. 安装依赖
pip3 install -r requirements.txt

# 6. 配置环境变量
cp .env.example .env
nano .env

# 7. 使用 systemd 或 screen 运行（见上文）
```

#### 阿里云/腾讯云

与 AWS EC2 类似，主要步骤：
1. 创建 ECS 实例（Ubuntu 20.04 或更高）
2. 配置安全组（允许出站访问）
3. SSH 连接到服务器
4. 按照上述 VPS 部署步骤操作

## 🔧 配置说明

### 环境变量（.env 文件）

```env
# 必填项
TELEGRAM_BOT_TOKEN=your_bot_token_here

# 可选项（有默认值）
ADMIN_USER_ID=123456789
CHECK_INTERVAL=5
DATABASE_PATH=lottery.db
TIMEZONE=Asia/Shanghai
LOTTERY_TIME=21:32:32
```

### 配置项说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ 是 | 无 | Telegram Bot Token |
| `ADMIN_USER_ID` | ❌ 否 | 无 | 管理员用户ID |
| `CHECK_INTERVAL` | ❌ 否 | 5 | 检查间隔（分钟） |
| `DATABASE_PATH` | ❌ 否 | lottery.db | 数据库文件路径 |
| `TIMEZONE` | ❌ 否 | Asia/Shanghai | 时区设置 |
| `LOTTERY_TIME` | ❌ 否 | 21:32:32 | 开奖时间 |

## 📊 数据库管理

### 备份数据库

```bash
# 手动备份
cp lottery.db lottery.db.backup

# 定时备份（添加到 crontab）
0 2 * * * cp /path/to/fcbot/lottery.db /path/to/backups/lottery.db.$(date +\%Y\%m\%d)
```

### 恢复数据库

```bash
# 停止机器人
sudo systemctl stop fcbot

# 恢复数据库
cp lottery.db.backup lottery.db

# 启动机器人
sudo systemctl start fcbot
```

### 清理旧数据

```bash
# 连接到数据库
sqlite3 lottery.db

# 删除6个月前的数据
DELETE FROM lottery_history WHERE open_time < datetime('now', '-6 months');

# 退出
.exit
```

## 🔍 故障排查

### 问题：机器人不响应

1. 检查机器人是否在运行
```bash
sudo systemctl status fcbot
# 或
ps aux | grep bot.py
```

2. 查看日志
```bash
sudo journalctl -u fcbot -n 50
# 或
tail -f logs/bot.log
```

3. 检查 Token 是否正确
```bash
cat .env | grep TOKEN
```

4. 测试网络连接
```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe
```

### 问题：无法获取开奖数据

1. 检查 API 是否可访问
```bash
curl https://macaumarksix.com/api/macaujc2.com
```

2. 检查日志中的错误信息
```bash
grep "Error" logs/bot.log
```

3. 手动触发检查
```python
# 在 Python 中测试
from bot import APIHandler
result = APIHandler.get_latest_result()
print(result)
```

### 问题：数据库锁定

```bash
# 检查数据库完整性
sqlite3 lottery.db "PRAGMA integrity_check;"

# 如果损坏，从备份恢复
cp lottery.db.backup lottery.db
```

### 问题：内存不足

```bash
# 查看内存使用
free -h

# 限制 Python 内存使用（在 systemd 服务文件中）
[Service]
MemoryLimit=256M
```

## 📈 性能优化

### 1. 数据库优化

```sql
-- 定期清理和优化
VACUUM;
ANALYZE;

-- 添加索引（已在代码中实现）
CREATE INDEX IF NOT EXISTS idx_expect ON lottery_history(expect);
CREATE INDEX IF NOT EXISTS idx_tema ON lottery_history(tema);
```

### 2. 日志轮转

创建 `/etc/logrotate.d/fcbot`：

```
/path/to/fcbot/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 3. 进程监控

使用 `supervisor` 或 `pm2` 进行进程管理：

```bash
# 安装 supervisor
sudo apt install supervisor

# 创建配置文件 /etc/supervisor/conf.d/fcbot.conf
[program:fcbot]
directory=/path/to/fcbot
command=/path/to/fcbot/venv/bin/python bot.py
autostart=true
autorestart=true
stderr_logfile=/var/log/fcbot.err.log
stdout_logfile=/var/log/fcbot.out.log

# 重载配置
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start fcbot
```

## 🔐 安全建议

1. **不要暴露 Token**
   - 永远不要将 `.env` 文件提交到 Git
   - 使用 `.gitignore` 排除敏感文件

2. **限制文件权限**
```bash
chmod 600 .env
chmod 600 lottery.db
```

3. **定期更新依赖**
```bash
pip install --upgrade -r requirements.txt
```

4. **配置防火墙**
```bash
# Ubuntu UFW
sudo ufw allow 22/tcp  # SSH
sudo ufw enable
```

5. **使用 HTTPS 反向代理**（如果需要 Web 界面）
```bash
sudo apt install nginx
# 配置 Nginx 反向代理
```

## 📱 监控和告警

### 使用 Telegram 机器人本身监控

在代码中添加心跳检测：

```python
# 每小时向管理员发送状态报告
async def send_heartbeat():
    if ADMIN_USER_ID:
        await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text="✅ 机器人运行正常"
        )
```

### 使用外部监控工具

- **UptimeRobot**: 监控机器人是否在线
- **Prometheus + Grafana**: 监控系统资源
- **Sentry**: 错误追踪

## 🔄 更新部署

### 更新代码

```bash
# 1. 停止机器人
sudo systemctl stop fcbot

# 2. 拉取最新代码
git pull origin main

# 3. 更新依赖
pip install -r requirements.txt --upgrade

# 4. 备份数据库
cp lottery.db lottery.db.backup

# 5. 启动机器人
sudo systemctl start fcbot

# 6. 检查状态
sudo systemctl status fcbot
```

### 回滚版本

```bash
# 1. 停止机器人
sudo systemctl stop fcbot

# 2. 回滚代码
git checkout <previous-commit-hash>

# 3. 恢复数据库（如果需要）
cp lottery.db.backup lottery.db

# 4. 启动机器人
sudo systemctl start fcbot
```

## 📞 技术支持

如遇到问题，请：

1. 查看 [常见问题](README.md#常见问题)
2. 检查日志文件
3. 在 GitHub 提交 Issue
4. 参考 [故障排查](#故障排查) 部分

## 📝 附录

### A. 完整的 systemd 服务文件示例

```ini
[Unit]
Description=Macau Lottery Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/fcbot
Environment="PATH=/home/ubuntu/fcbot/venv/bin:/usr/bin"
ExecStart=/home/ubuntu/fcbot/venv/bin/python /home/ubuntu/fcbot/bot.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/fcbot/bot.log
StandardError=append:/var/log/fcbot/error.log

# 安全设置
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/home/ubuntu/fcbot

# 资源限制
MemoryLimit=512M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
```

### B. Nginx 配置示例（如果需要 webhook）

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location /webhook {
        proxy_pass http://localhost:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### C. 自动部署脚本

```bash
#!/bin/bash
# deploy.sh - 自动部署脚本

set -e

echo "🚀 开始部署..."

# 停止服务
echo "⏸ 停止服务..."
sudo systemctl stop fcbot

# 备份数据库
echo "💾 备份数据库..."
cp lottery.db lottery.db.backup.$(date +%Y%m%d_%H%M%S)

# 拉取代码
echo "📥 拉取最新代码..."
git pull origin main

# 更新依赖
echo "📦 更新依赖..."
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 启动服务
echo "▶️ 启动服务..."
sudo systemctl start fcbot

# 检查状态
echo "🔍 检查状态..."
sleep 5
sudo systemctl status fcbot

echo "✅ 部署完成！"
```

使用方法：
```bash
chmod +x deploy.sh
./deploy.sh
```

---

**祝部署顺利！** 🎉
