"""Monitor do Diário Oficial do MPMG.

Baixa a edição do dia, procura os nomes configurados e envia push via ntfy.
Uso:
    py monitor_diario.py                 # verifica a edição de hoje
    py monitor_diario.py --data 2026-10-30   # verifica uma data específica
    py monitor_diario.py --nome "TEXTO"  # procura outro texto (teste)
    py monitor_diario.py --teste-push    # envia um push de teste
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import pymupdf

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"
ESTADO = BASE / "estado.json"
LOG = BASE / "monitor.log"

PORTAL = "https://www.mpmg.mp.br/portal/menu/servicos/diario-oficial/"
PDF_URL = "https://www.mpmg.mp.br/diariooficial/DO-{:%Y%m%d}.PDF"
UA = {"User-Agent": "Mozilla/5.0 (monitor-diario-mpmg)"}


def log(msg):
    linha = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(linha)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def normalizar(texto):
    # Remove acentos, hifenização de fim de linha e espaços duplicados.
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"-\s*\n\s*", "", texto)
    return re.sub(r"\s+", " ", texto).upper()


def baixar(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def url_da_edicao(data):
    """Confere no portal se a edição do dia foi publicada; cai no padrão de nome se o portal falhar."""
    alvo = f"DO-{data:%Y%m%d}"
    try:
        html = baixar(PORTAL).decode("utf-8", "ignore")
        links = re.findall(r'href="([^"]*diariooficial/[^"]+\.pdf)"', html, re.I)
        do_dia = [l for l in links if alvo.lower() in l.lower()]
        if do_dia:
            return [urllib.request.urljoin(PORTAL, l) for l in dict.fromkeys(do_dia)]
    except urllib.error.URLError as e:
        log(f"Portal indisponível ({e}); tentando o endereço padrão do PDF.")
    return [PDF_URL.format(data)]


LIMITE_PUBLICACAO = 1500
RESPONSAVEL = re.compile(r"^RESPONSAVEL\s*:")
RODAPE = re.compile(r"^(https?://\S*diariooficial\S*|Edição de \d\d/\d\d/\d{4}|Página \d+ de \d+)$", re.I)


def linhas_do_pdf(doc):
    """Linhas do PDF inteiro em sequência (sem o rodapé), com página e margem direita de cada uma."""
    linhas = []
    for p, pagina in enumerate(doc, start=1):
        for bloco in pagina.get_text("dict")["blocks"]:
            for l in bloco.get("lines", []):
                texto = "".join(s["text"] for s in l["spans"]).strip()
                if texto and not RODAPE.match(texto):
                    linhas.append({"texto": texto, "x1": l["bbox"][2], "pagina": p})
    return linhas


def juntar_linhas(linhas):
    """Junta linhas quebradas pelo PDF, desfazendo a hifenização de fim de linha."""
    texto = ""
    for l in linhas:
        l = l.strip()
        if not l:
            continue
        if texto.endswith("-") and not texto.endswith(" -"):
            texto = texto[:-1] + l
        else:
            texto += (" " if texto else "") + l
    return re.sub(r"\s+", " ", texto)


def extrair_publicacao(linhas, ini, fim):
    """Devolve o texto da publicação que contém as linhas ini..fim (onde está o nome).

    Nas listas de procedimentos o nome aparece numa linha "RESPONSÁVEL: ..." que vem
    depois dos itens a que se refere; aí a publicação são os itens desde o
    "RESPONSÁVEL:" anterior. Nos demais casos é o parágrafo: as quebras de linha do
    PDF caem no meio das frases, então o parágrafo termina na linha que acaba em ponto
    ou que não chega à margem direita.
    """
    norm = [normalizar(l["texto"]).strip() for l in linhas]
    margem = max(l["x1"] for l in linhas)
    texto = lambda a, b: juntar_linhas(l["texto"] for l in linhas[a:b + 1])
    if RESPONSAVEL.match(norm[ini]):
        a = ini
        while a > 0 and not RESPONSAVEL.match(norm[a - 1]) and ini - a < 40:
            a -= 1
        return texto(a, fim)
    termina_frase = lambda k: norm[k].endswith((".", ":", ";"))
    a = ini
    while a > 0 and not termina_frase(a - 1) and not norm[a].startswith("- ") and ini - a < 15:
        a -= 1
    b = fim
    while (b < len(linhas) - 1 and not termina_frase(b) and linhas[b]["x1"] > margem - 30
           and b - fim < 15):
        b += 1
    return texto(a, b)


def procurar(pdf_bytes, nomes):
    achados = []
    with pymupdf.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        linhas = linhas_do_pdf(doc)
    # Texto normalizado do PDF com o índice da linha de cada caractere, para achar o
    # nome mesmo quando ele quebra de uma linha (ou página) para a outra.
    texto, dono = "", []
    for n, l in enumerate(linhas):
        parte = normalizar(l["texto"]).strip()
        if texto.endswith("-") and not texto.endswith(" -"):
            texto = texto[:-1]
            dono.pop()
        elif texto:
            texto += " "
            dono.append(n)
        texto += parte
        dono += [n] * len(parte)
    vistos = set()
    for nome in nomes:
        for m in re.finditer(re.escape(normalizar(nome).strip()), texto):
            ini, fim = dono[m.start()], dono[m.end() - 1]
            publicacao = extrair_publicacao(linhas, ini, fim)
            if publicacao in vistos:
                continue
            vistos.add(publicacao)
            if len(publicacao) > LIMITE_PUBLICACAO:
                publicacao = publicacao[:LIMITE_PUBLICACAO].rsplit(" ", 1)[0] + " [...]"
            achados.append({"pagina": linhas[ini]["pagina"], "nome": nome, "trecho": publicacao})
    return achados


def ntfy_base(cfg):
    servidor = cfg.get("ntfy_servidor", "https://ntfy.sh").rstrip("/")
    return f"{servidor}/{cfg['ntfy_topico']}"


def ja_notificado(cfg, marca):
    """Consulta o histórico do tópico no ntfy: evita aviso duplicado entre GitHub Actions e o PC."""
    try:
        req = urllib.request.Request(f"{ntfy_base(cfg)}/json?poll=1&since=72h", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            for linha in r.read().decode("utf-8").splitlines():
                if marca in json.loads(linha).get("tags", []):
                    return True
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log(f"Não foi possível consultar o histórico do ntfy ({e}); o aviso será enviado mesmo assim.")
    return False


def notificar(cfg, titulo, mensagem, url=None, prioridade="high", marca=None):
    tags = "newspaper" + (f",{marca}" if marca else "")
    headers = {"Title": titulo.encode("utf-8"), "Priority": prioridade, "Tags": tags}
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Abrir PDF, {url}"
    req = urllib.request.Request(ntfy_base(cfg), data=mensagem.encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def carregar(caminho, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="AAAA-MM-DD (padrão: hoje)")
    ap.add_argument("--nome", action="append", help="texto a procurar (substitui o config)")
    ap.add_argument("--teste-push", action="store_true")
    ap.add_argument("--sem-push", action="store_true", help="não envia notificação")
    args = ap.parse_args()

    # No GitHub Actions a configuração vem de secrets (variáveis de ambiente), sem config.json.
    cfg = carregar(CONFIG, {})
    if os.environ.get("NTFY_TOPICO"):
        cfg["ntfy_topico"] = os.environ["NTFY_TOPICO"]
    if os.environ.get("NOMES"):
        cfg["nomes"] = [n.strip() for n in os.environ["NOMES"].split(";") if n.strip()]
    if not cfg.get("ntfy_topico") or not cfg.get("nomes"):
        sys.exit(f"Configuração incompleta: crie {CONFIG} ou defina NTFY_TOPICO e NOMES.")

    if args.teste_push:
        notificar(cfg, "Monitor do Diário Oficial MPMG", "Push de teste: as notificações estão funcionando.", prioridade="default")
        log("Push de teste enviado.")
        return

    data = dt.date.fromisoformat(args.data) if args.data else dt.date.today()
    nomes = args.nome or cfg["nomes"]
    estado = carregar(ESTADO, {})
    chave = f"{data:%Y-%m-%d}"

    # Execuções repetidas no mesmo dia (09h, 12h, 16h) só reprocessam se a edição ainda não foi lida.
    if not args.data and not args.nome and estado.get(chave, {}).get("verificado"):
        log(f"Edição de {chave} já verificada hoje; nada a fazer.")
        return

    encontrou_pdf = falha_acesso = False
    achados, urls_lidas = [], []
    for url in url_da_edicao(data):
        try:
            pdf = baixar(url)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                falha_acesso = True
            log(f"{url}: HTTP {e.code} (edição ainda não publicada, inexistente ou acesso bloqueado).")
            continue
        except urllib.error.URLError as e:
            falha_acesso = True
            log(f"{url}: falha de rede ({e}).")
            continue
        if not pdf.startswith(b"%PDF"):
            log(f"{url}: resposta não é PDF.")
            continue
        encontrou_pdf = True
        urls_lidas.append(url)
        r = procurar(pdf, nomes)
        for a in r:
            a["url"] = url
        achados += r
        log(f"{url}: {len(pdf)//1024} KB lidos, {len(r)} ocorrência(s).")

    if not encontrou_pdf:
        log(f"Nenhuma edição disponível para {chave}.")
        if falha_acesso:
            # Código de saída 1 faz o GitHub Actions marcar a execução como falha e avisar por e-mail.
            sys.exit("Não foi possível acessar o site do MPMG.")
        return

    if achados:
        paginas = sorted({a["pagina"] for a in achados})
        corpo = (f"Seu nome aparece no Diário Oficial do MPMG de {data:%d/%m/%Y}, "
                 f"página(s) {', '.join(map(str, paginas))}.")
        for a in achados:
            corpo += f"\n\n[p. {a['pagina']}] {a['trecho']}"
            log(f"  p.{a['pagina']}: {a['trecho']}")
        # O ntfy transforma em anexo mensagens acima de 4096 bytes; corta antes disso.
        if len(corpo.encode("utf-8")) > 3900:
            corpo = corpo.encode("utf-8")[:3850].decode("utf-8", "ignore").rsplit(" ", 1)[0]
            corpo += " [...]\n\n(texto cortado; veja o PDF)"
        marca = f"do-{data:%Y%m%d}"
        if args.sem_push:
            pass
        elif ja_notificado(cfg, marca):
            log("Aviso desta edição já foi enviado (pelo GitHub ou pelo PC); não repetido.")
        else:
            notificar(cfg, f"Diário Oficial MPMG {data:%d/%m}: você foi citado", corpo,
                      url=achados[0]["url"], marca=marca)
            log("Notificação enviada.")
    elif cfg.get("avisar_quando_nada_encontrado") and not args.sem_push:
        notificar(cfg, f"Diário Oficial MPMG {data:%d/%m}", "Edição verificada: nenhuma publicação com seu nome.",
                  url=urls_lidas[0], prioridade="min")

    if not args.data and not args.nome:
        estado[chave] = {"verificado": True, "ocorrencias": len(achados), "urls": urls_lidas}
        ESTADO.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # registra qualquer falha inesperada no log da tarefa agendada
        log(f"ERRO: {e!r}")
        raise
