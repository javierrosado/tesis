# Uso: source scripts/load_env.sh   (carga ../secrets/.env sin imprimir valores; tolera BOM y CRLF)
_ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/secrets/.env"
if [ -f "$_ENV_FILE" ]; then set -a; source <(sed -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' "$_ENV_FILE"); set +a; echo "env cargado"; else echo "falta $_ENV_FILE"; fi
