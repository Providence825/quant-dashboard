#!/bin/bash
# 守投者部署脚本 - Alibaba Cloud Linux 4 专用版
# 在阿里云网页终端中执行

set -e

echo "========================================"
echo "守投者量化系统 - 阿里云部署脚本"
echo "服务器: Alibaba Cloud Linux 4"
echo "========================================"

# 1. 创建工作目录
echo "[1/9] 创建工作目录..."
cd /opt
mkdir -p shoutouzhehuzhe
cd shoutouzhehuzhe

# 2. 安装系统依赖
echo "[2/9] 安装系统依赖（Python、Nginx、Git）..."
yum install -y python3.11 python3.11-pip python3.11-devel gcc gcc-c++ nginx git

# 3. 创建 Python 虚拟环境
echo "[3/9] 创建 Python 虚拟环境..."
python3.11 -m venv venv
source venv/bin/activate

# 4. 升级 pip
echo "[4/9] 升级 pip..."
pip install --upgrade pip

# 5. 安装 Python 依赖（先安装基础包）
echo "[5/9] 安装 Python 依赖..."
pip install flask requests numpy pandas apscheduler python-dotenv
pip install gunicorn gevent

echo "✅ 基础依赖安装完成"
echo ""
echo "========================================"
echo "⚠️  接下来需要手动操作："
echo "========================================"
echo ""
echo "1. 上传代码压缩包到 /opt/ 目录"
echo "   文件名: shoutouzhe-deploy.tar.gz"
echo ""
echo "2. 解压代码："
echo "   cd /opt/shoutouzhehuzhe"
echo "   tar -xzf /opt/shoutouzhe-deploy.tar.gz"
echo ""
echo "3. 安装项目依赖："
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "4. 配置环境变量："
echo "   cp .env.template .env"
echo "   nano .env"
echo "   # 修改 DEEPSEEK_API_KEY"
echo ""
echo "5. 创建并启动服务："
echo "   bash /opt/shoutouzhehuzhe/deploy/setup-service.sh"
echo ""
