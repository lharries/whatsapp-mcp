#!/bin/bash
# ============================================================
#  setup_vps.sh — Instalacao do Agente Cismetro na VPS Ubuntu
#  Execute como root: sudo bash setup_vps.sh
# ============================================================
set -e

INSTALL_DIR="/opt/cismetro"
BRIDGE_REPO="https://github.com/lharries/whatsapp-mcp"
GO_VERSION="1.22.4"
PYTHON_SCRIPT="relatorio_agente.py"
SERVICE_USER="cismetro"

echo ""
echo "============================================================"
echo "  AGENTE CISMETRO - Setup VPS Ubuntu/Debian"
echo "============================================================"
echo ""

# ── 1. Dependencias do sistema ────────────────────────────────
echo "[1/7] Instalando dependencias do sistema..."
apt-get update -qq
apt-get install -y -qq \
    git curl wget build-essential \
    gcc libsqlite3-dev \
    python3 python3-pip python3-venv \
    openssh-server rsync

# ── 2. Go (para compilar o bridge) ───────────────────────────
if ! command -v go &>/dev/null; then
    echo "[2/7] Instalando Go ${GO_VERSION}..."
    wget -q "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -O /tmp/go.tar.gz
    tar -C /usr/local -xzf /tmp/go.tar.gz
    echo 'export PATH=$PATH:/usr/local/go/bin' >> /etc/profile
    export PATH=$PATH:/usr/local/go/bin
else
    echo "[2/7] Go ja instalado: $(go version)"
fi

# ── 3. Usuario e diretorios ───────────────────────────────────
echo "[3/7] Criando usuario e diretorios..."
id -u $SERVICE_USER &>/dev/null || useradd -r -s /bin/bash -m -d $INSTALL_DIR $SERVICE_USER

mkdir -p $INSTALL_DIR/{bridge,store,relatorios,logs}
chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR

# Pasta relatorios acessivel via SFTP (grupo sftp-users)
groupadd -f sftp-users
usermod -aG sftp-users $SERVICE_USER
chmod 755 $INSTALL_DIR/relatorios

# ── 4. Bridge (compilar do fonte) ────────────────────────────
echo "[4/7] Baixando e compilando whatsapp-bridge..."
if [ ! -d "/tmp/whatsapp-mcp" ]; then
    git clone --depth=1 $BRIDGE_REPO /tmp/whatsapp-mcp
fi

cd /tmp/whatsapp-mcp/whatsapp-bridge
export PATH=$PATH:/usr/local/go/bin
go mod tidy
CGO_ENABLED=1 go build -o $INSTALL_DIR/bridge/whatsapp-bridge .
chmod +x $INSTALL_DIR/bridge/whatsapp-bridge
echo "    Bridge compilado: $(ls -lh $INSTALL_DIR/bridge/whatsapp-bridge | awk '{print $5}')"

# ── 5. Python venv + dependencias ────────────────────────────
echo "[5/7] Configurando ambiente Python..."
python3 -m venv $INSTALL_DIR/venv
$INSTALL_DIR/venv/bin/pip install -q --upgrade pip
$INSTALL_DIR/venv/bin/pip install -q openpyxl requests

# Copia script do agente
cp /tmp/whatsapp-mcp/relatorio_agente_linux.py $INSTALL_DIR/relatorio_agente.py
# (ou use o arquivo enviado via scp)
chown $SERVICE_USER:$SERVICE_USER $INSTALL_DIR/relatorio_agente.py

# ── 6. Systemd service para o bridge ─────────────────────────
echo "[6/7] Criando servico systemd para o bridge..."
cat > /etc/systemd/system/whatsapp-bridge.service << 'EOF'
[Unit]
Description=WhatsApp Bridge (Cismetro)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=cismetro
WorkingDirectory=/opt/cismetro/bridge
ExecStart=/opt/cismetro/bridge/whatsapp-bridge
Restart=on-failure
RestartSec=10
StandardOutput=append:/opt/cismetro/logs/bridge.log
StandardError=append:/opt/cismetro/logs/bridge.log
Environment=HOME=/opt/cismetro

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable whatsapp-bridge
echo "    Servico criado. Use: systemctl start whatsapp-bridge"

# ── 7. Cron para relatorio semanal ───────────────────────────
echo "[7/7] Configurando cron (toda segunda-feira as 07:00)..."
CRON_JOB="0 7 * * 1 $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/relatorio_agente.py 7 >> $INSTALL_DIR/logs/agente.log 2>&1"
(crontab -u $SERVICE_USER -l 2>/dev/null; echo "$CRON_JOB") | crontab -u $SERVICE_USER -

echo ""
echo "============================================================"
echo "  INSTALACAO CONCLUIDA!"
echo "============================================================"
echo ""
echo "  PROXIMO PASSO: copiar a sessao do WhatsApp do seu PC:"
echo ""
echo "  No seu PC Windows (PowerShell):"
echo "    scp -r C:\Users\eduar\store\* usuario@IP_DA_VPS:/opt/cismetro/store/"
echo ""
echo "  Depois, inicie o bridge:"
echo "    systemctl start whatsapp-bridge"
echo "    systemctl status whatsapp-bridge"
echo ""
echo "  Para gerar relatorio manualmente:"
echo "    sudo -u cismetro /opt/cismetro/venv/bin/python3 /opt/cismetro/relatorio_agente.py 30"
echo ""
echo "  Relatorios ficam em: /opt/cismetro/relatorios/"
echo "  Acesse via SFTP:     sftp usuario@IP_DA_VPS"
echo "                       cd /opt/cismetro/relatorios"
echo "============================================================"
