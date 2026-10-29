# 守投者量化系统 - 部署指南

## 🚀 方案1：一键脚本部署（推荐）

### 准备工作
1. 购买云服务器（阿里云/腾讯云轻量应用服务器）
   - 配置：2核4G，40GB 硬盘
   - 系统：Ubuntu 22.04 LTS
   - 开放端口：80、443

2. 上传代码到服务器
```bash
# 方式A：Git 克隆
ssh root@your-server-ip
cd /opt
git clone https://your-repo-url.git shoutouzhehuzhe

# 方式B：本地打包上传
# 本地执行（Windows PowerShell）：
cd C:\Users\20137\shoutouzhehuzhe
tar -czf shoutouzhe.tar.gz --exclude=__pycache__ --exclude=*.db --exclude=.env .
scp shoutouzhe.tar.gz root@your-server-ip:/opt/

# 服务器执行：
ssh root@your-server-ip
cd /opt
mkdir shoutouzhehuzhe
tar -xzf shoutouzhe.tar.gz -C shoutouzhehuzhe
```

### 一键部署
```bash
cd /opt/shoutouzhehuzhe/deploy
chmod +x install.sh
sudo ./install.sh
```

### 配置 API Key
```bash
nano /opt/shoutouzhehuzhe/.env
# 修改 DEEPSEEK_API_KEY=sk-your-real-key-here
# Ctrl+O 保存，Ctrl+X 退出

systemctl restart shoutouzhe
```

### 验证部署
```bash
# 查看服务状态
systemctl status shoutouzhe

# 查看实时日志
journalctl -u shoutouzhe -f

# 测试访问
curl http://localhost:5000/shoutouzhe
```

---

## 🐳 方案2：Docker 容器部署

### 安装 Docker
```bash
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
```

### 构建并启动
```bash
cd /opt/shoutouzhehuzhe

# 复制环境变量模板
cp .env.template .env
nano .env  # 填写真实的 DEEPSEEK_API_KEY

# 启动容器
cd deploy
docker-compose up -d

# 查看日志
docker-compose logs -f shoutouzhe
```

### 常用命令
```bash
# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 更新代码后重新构建
docker-compose up -d --build

# 进入容器调试
docker exec -it shoutouzhe bash
```

---

## 🔒 配置 HTTPS（推荐）

### 使用 Certbot 自动申请 Let's Encrypt 证书
```bash
# 安装 Certbot
apt install -y certbot python3-certbot-nginx

# 自动配置 SSL（需要先配置域名解析）
certbot --nginx -d your-domain.com

# 测试自动续期
certbot renew --dry-run

# 设置自动续期（每月1号凌晨2点）
crontab -e
# 添加：0 2 1 * * certbot renew --quiet
```

---

## 📊 监控与维护

### 性能监控
```bash
# CPU/内存监控
htop

# 磁盘空间
df -h

# 实时连接数
netstat -an | grep :80 | wc -l

# 查看 Nginx 访问日志
tail -f /var/log/nginx/access.log
```

### 日志管理
```bash
# 配置日志轮转（防止日志占满磁盘）
cat > /etc/logrotate.d/shoutouzhe << 'EOF'
/opt/shoutouzhehuzhe/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        systemctl reload shoutouzhe > /dev/null 2>&1 || true
    endscript
}
EOF
```

### 数据库备份
```bash
# 创建备份脚本
cat > /opt/backup_db.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=/opt/backups
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf $BACKUP_DIR/shoutouzhe_db_$DATE.tar.gz /opt/shoutouzhehuzhe/data/*.db
find $BACKUP_DIR -mtime +7 -name "*.tar.gz" -delete  # 删除7天前的备份
EOF

chmod +x /opt/backup_db.sh

# 设置每日凌晨3点自动备份
crontab -e
# 添加：0 3 * * * /opt/backup_db.sh
```

---

## ⚠️ 故障排查

### 服务无法启动
```bash
# 查看详细错误日志
journalctl -u shoutouzhe -xe

# 检查端口占用
netstat -tlnp | grep 5000

# 手动启动测试
cd /opt/shoutouzhehuzhe
source venv/bin/activate
python run.py
```

### 502 Bad Gateway
- 检查 Gunicorn 服务是否运行：`systemctl status shoutouzhe`
- 检查防火墙：`ufw status`
- 查看 Nginx 错误日志：`tail -f /var/log/nginx/error.log`

### AI 功能不可用
- 检查 .env 中的 DEEPSEEK_API_KEY 是否正确
- 测试 API：`curl -H "Authorization: Bearer sk-xxx" https://api.deepseek.com/chat/completions`
- 查看应用日志中的错误信息

---

## 📞 技术支持

如遇到部署问题，请提供以下信息：
1. 操作系统版本：`cat /etc/os-release`
2. Python 版本：`python3 --version`
3. 服务状态：`systemctl status shoutouzhe`
4. 错误日志：`journalctl -u shoutouzhe -n 50`
