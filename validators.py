import re
from urllib.parse import urlparse


EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
USERNAME_RE = re.compile(r"^@?[A-Za-z0-9._]{2,30}$")


def validar_email(texto: str) -> tuple[bool, str, str]:
    email = (texto or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):
        return False, email, "⚠️ Envie um e-mail válido. Exemplo: cliente@email.com"
    return True, email, ""


def _dominio(hostname: str) -> str:
    host = (hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _limpar_url(texto: str) -> str:
    texto = (texto or "").strip()
    texto = texto.split()[0] if texto.split() else texto
    return texto.rstrip(".,;)")


def _url_com_scheme(texto: str) -> str:
    if re.match(r"^https?://", texto, re.IGNORECASE):
        return texto
    if "." in texto and not texto.startswith("@"):
        return "https://" + texto
    return texto


def validar_instagram(texto: str) -> tuple[bool, str, str]:
    bruto = _limpar_url(texto)
    if not bruto:
        return False, bruto, "⚠️ Envie o @ ou link do Instagram. Exemplo: @usuario ou https://instagram.com/usuario"

    if bruto.startswith("@") or (USERNAME_RE.fullmatch(bruto) and "." not in bruto):
        usuario = bruto if bruto.startswith("@") else f"@{bruto}"
        return True, usuario, ""

    url = _url_com_scheme(bruto)
    parsed = urlparse(url)
    host = _dominio(parsed.hostname or "")
    if host not in {"instagram.com", "m.instagram.com", "instagr.am", "threads.net"}:
        return False, bruto, "⚠️ Esse link não parece ser do Instagram. Envie @usuario ou link instagram.com/..."
    if not parsed.path or parsed.path.strip("/") == "":
        return False, bruto, "⚠️ O link do Instagram precisa apontar para perfil, post, reels ou story."
    return True, url, ""


def validar_tiktok(texto: str) -> tuple[bool, str, str]:
    bruto = _limpar_url(texto)
    if not bruto:
        return False, bruto, "⚠️ Envie o @ ou link do TikTok. Exemplo: @usuario ou https://tiktok.com/@usuario"

    if bruto.startswith("@") or (USERNAME_RE.fullmatch(bruto) and "." not in bruto):
        usuario = bruto if bruto.startswith("@") else f"@{bruto}"
        return True, usuario, ""

    url = _url_com_scheme(bruto)
    parsed = urlparse(url)
    host = _dominio(parsed.hostname or "")
    dominios = {"tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}
    if host not in dominios:
        return False, bruto, "⚠️ Esse link não parece ser do TikTok. Envie @usuario ou link tiktok.com/..."
    if host in {"tiktok.com", "m.tiktok.com"} and (not parsed.path or parsed.path.strip("/") == ""):
        return False, bruto, "⚠️ O link do TikTok precisa apontar para perfil ou vídeo."
    return True, url, ""


def validar_destino_pedido(pedido: dict, texto: str) -> tuple[bool, str, str]:
    catalogo = str((pedido or {}).get("catalogo") or "").lower()
    if "iptv" in catalogo or "internet" in catalogo:
        return validar_email(texto)
    if "instagram" in catalogo:
        return validar_instagram(texto)
    if "tiktok" in catalogo:
        return validar_tiktok(texto)

    destino = (texto or "").strip()
    if len(destino) < 3:
        return False, destino, "⚠️ Envie um link, @ ou identificação válida para o pedido."
    return True, destino, ""
