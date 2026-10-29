#!/bin/bash
# 守投者 - 配置 systemd 服务和 Nginx

set -e

echo "========================================"
echo "配置守投者服务"
echo "========================================"

# 1. 创建 systemd 服务
echo "[1/3] 创建 systemd 服务..."
cat > /etc/systemd/system/shoutouzhe.service << 'EOF'
[Unit]
Description=守投者量化系统
After=network.target

[Service]
Type=notify
User=root
WorkingDirectory=/opt/shoutouzhehuzhe
Environment="PATH=/opt/shoutouzhehuzhe/venv/bin"
ExecStart=/opt/shoutouzhehuzhe/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 --timeout 120 --worker-class gevent run:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable shoutouzhe

# 2. 配置 Nginx
echo "[2/3] 配置 Nginx..."
cat > /etc/nginx/conf.d/shoutouzhe.conf << 'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    location /static/ {
        alias /opt/shoutouzhehuzhe/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
EOF

nginx -t
systemctl enable nginx
systemctl restart nginx

# 3. 启动服务
echo "[3/3] 启动守投者服务..."
systemctl start shoutouzhe

echo ""
echo "========================================"
echo "✅ 部署完成！"
echo "========================================"
echo ""
echo "访问地址: http://39.96.58.26/shoutouzhe"
echo ""
echo "查看服务状态: systemctl status shoutouzhe"
echo "查看实时日志: journalctl -u shoutouzhe -f"
echo "重启服务: systemctl restart shoutouzhe"
echo ""
