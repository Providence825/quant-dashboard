#!/bin/bash
# 守投者量化系统 - 一键部署脚本（Ubuntu 22.04 / CentOS 8）
# 使用方法：chmod +x install.sh && sudo ./install.sh

set -e  # 遇到错误立即退出

echo "========================================"
echo "守投者量化系统 - 自动部署脚本"
echo "========================================"

# 检测操作系统
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "无法检测操作系统"
    exit 1
fi

# 1. 安装 Python 3.13 和依赖
echo "[1/8] 安装系统依赖..."
if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    apt update
    apt install -y python3.13 python3.13-venv python3-pip nginx git
elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ]; then
    yum install -y python3.13 python3.13-venv python3-pip nginx git
else
    echo "不支持的操作系统: $OS"
    exit 1
fi

# 2. 创建部署目录
echo "[2/8] 创建部署目录..."
mkdir -p /opt/shoutouzhehuzhe
cd /opt/shoutouzhehuzhe

# 3. 创建虚拟环境
echo "[3/8] 创建 Python 虚拟环境..."
python3.13 -m venv venv
source venv/bin/activate

# 4. 安装 Python 依赖
echo "[4/8] 安装 Python 依赖..."
if [ -f requirements.txt ]; then
    pip install --no-cache-dir -r requirements.txt
    pip install gunicorn gevent
else
    echo "警告: 未找到 requirements.txt，请手动安装依赖"
fi

# 5. 创建环境变量文件
echo "[5/8] 配置环境变量..."
if [ ! -f .env ]; then
    cat > .env << 'EOF'
FLASK_SECRET_KEY=change-this-to-random-secret-key
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
DEEPSEEK_MODEL=deepseek-chat
READONLY=false
HTD_ONLY=false
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
EOF
    chmod 600 .env
    echo "✅ 已创建 .env 文件，请编辑填写真实的 API Key"
else
    echo "✅ .env 文件已存在，跳过"
fi

# 6. 创建 systemd 服务
echo "[6/8] 配置 systemd 服务..."
cat > /etc/systemd/system/shoutouzhe.service << EOF
[Unit]
Description=守投者量化系统
After=network.target

[Service]
Type=notify
User=root
WorkingDirectory=/opt/shoutouzhehuzhe
Environment="PATH=/opt/shoutouzhehuzhe/venv/bin"
ExecStart=/opt/shoutouzhehuzhe/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 --timeout 120 --worker-class gevent run:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable shoutouzhe

# 7. 配置 Nginx
echo "[7/8] 配置 Nginx 反向代理..."
cat > /etc/nginx/sites-available/shoutouzhe << 'EOF'
server {
    listen 80;
    server_name _;  # 改成你的域名或IP

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 支持（AI 流式输出）
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # 静态文件直接由 Nginx 服务
    location /static/ {
        alias /opt/shoutouzhehuzhe/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# 启用站点
if [ ! -L /etc/nginx/sites-enabled/shoutouzhe ]; then
    ln -s /etc/nginx/sites-available/shoutouzhe /etc/nginx/sites-enabled/
fi

# 删除默认站点（可选）
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx

# 8. 启动服务
echo "[8/8] 启动守投者服务..."
systemctl start shoutouzhe

echo ""
echo "========================================"
echo "✅ 部署完成！"
echo "========================================"
echo ""
echo "服务状态："
systemctl status shoutouzhe --no-pager -l
echo ""
echo "访问地址: http://$(hostname -I | awk '{print $1}')/shoutouzhe"
echo ""
echo "常用命令："
echo "  查看日志: journalctl -u shoutouzhe -f"
echo "  重启服务: systemctl restart shoutouzhe"
echo "  停止服务: systemctl stop shoutouzhe"
echo "  编辑配置: nano /opt/shoutouzhehuzhe/.env"
echo ""
echo "⚠️  重要提醒："
echo "  1. 请编辑 /opt/shoutouzhehuzhe/.env 填写真实的 DEEPSEEK_API_KEY"
echo "  2. 请修改 /etc/nginx/sites-available/shoutouzhe 中的 server_name"
echo "  3. 建议配置 HTTPS: certbot --nginx -d your-domain.com"
echo ""
