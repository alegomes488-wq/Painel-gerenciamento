#!/usr/bin/env bash
# Instala o atalho "Iniciar Painel CyberCore" no Ubuntu.
# Roda UMA vez; depois e so clicar duas vezes no atalho criado.
set -eu

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APP_DIR/cinecash-iniciar-painel.desktop"

chmod +x "$BASE_DIR/iniciar_sistema.sh"

mkdir -p "$APP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Iniciar Painel CyberCore
Comment=Sobe backend (7861) e painel admin (8080)
Exec=bash "$BASE_DIR/iniciar_sistema.sh"
Path=$BASE_DIR
Icon=utilities-terminal
Terminal=true
Categories=Development;
StartupNotify=false
EOF

chmod +x "$DESKTOP_FILE"
update-desktop-database "$APP_DIR" 2>/dev/null || true

criado=0
for desk in "$HOME/Desktop" "$HOME/Área de Trabalho" "$HOME/Área de trabalho"; do
    if [ -d "$desk" ]; then
        destino="$desk/Iniciar Painel CyberCore.desktop"
        cp "$DESKTOP_FILE" "$destino"
        chmod +x "$destino"
        gio set "$destino" metadata::trusted true 2>/dev/null || true
        echo "[OK] Atalho na area de trabalho: $destino"
        criado=1
    fi
done

echo "[OK] Atalho no menu de aplicativos: Iniciar Painel CyberCore"
if [ "$criado" = 0 ]; then
    echo "     (pasta da area de trabalho nao encontrada; use o menu de aplicativos)"
fi
echo
echo "Agora e so clicar duas vezes em 'Iniciar Painel CyberCore'."
echo "Na 1a vez o Ubuntu pode pedir 'Permitir Iniciar' (Trust and Launch) - clique e pronto."
