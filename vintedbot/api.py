"""API de linha de comandos para a Wintermute gerir as pesquisas (sem abrir uma porta nem outro processo).

    python -m vintedbot.api listar
    python -m vintedbot.api criar --texto=T [--preco-min=N] [--preco-max=N] [--nome=X]
    python -m vintedbot.api pausar|retomar|apagar --id=N

Escreve uma linha de JSON no stdout: o resultado, ou {"erro": "..."} com código de saída 1. Corre no diretório
do bot (lê o .env e a vintedbot.db de lá; o .env do bot ganha às variáveis herdadas de quem a chama). Uma pesquisa criada fica por "primar": o Monitor marca como vistos
os artigos da primeira leitura sem alertar, como no /add.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlencode

from vintedbot.storage import Search, Storage
from vintedbot.vinted.url_parser import parse_search_url

DOMINIO = "www.vinted.pt"
TEXTO_MAX = 100
PRECO_MAX = 10_000


class ErroApi(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # o argparse sairia com código 2 e texto no stderr
        raise ErroApi(f"Pedido inválido: {message}")


def _numero(valor: float) -> int | float:
    return int(valor) if float(valor).is_integer() else valor


def url_pesquisa(texto: str, preco_min: float | None, preco_max: float | None) -> str:
    params: list[tuple[str, str]] = [("search_text", texto)]
    if preco_min is not None:
        params.append(("price_from", str(_numero(preco_min))))
    if preco_max is not None:
        params.append(("price_to", str(_numero(preco_max))))
    params += [("currency", "EUR"), ("order", "newest_first")]
    return f"https://{DOMINIO}/catalog?{urlencode(params)}"


def _preco(params: dict[str, str], chave: str) -> int | float | None:
    try:
        return _numero(float(params[chave]))
    except (KeyError, ValueError):
        return None


def _para_json(s: Search) -> dict:
    return {
        "id": s.id, "nome": s.name, "ativa": s.active, "texto": s.params.get("search_text"),
        "preco_min": _preco(s.params, "price_from"), "preco_max": _preco(s.params, "price_to"), "url": s.url,
    }  # fmt: skip


def _parser() -> _Parser:
    parser = _Parser(prog="python -m vintedbot.api")
    ops = parser.add_subparsers(dest="op", required=True, parser_class=_Parser)
    ops.add_parser("listar")
    criar = ops.add_parser("criar")
    criar.add_argument("--texto", required=True)
    criar.add_argument("--preco-min")
    criar.add_argument("--preco-max")
    criar.add_argument("--nome")
    for op in ("pausar", "retomar", "apagar"):
        ops.add_parser(op).add_argument("--id", required=True, type=int)
    return parser


def _validar_preco(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        valor = float(raw)
    except ValueError as exc:
        raise ErroApi("Os preços têm de ser números.") from exc
    if not 0 <= valor <= PRECO_MAX:
        raise ErroApi(f"Os preços têm de estar entre 0 e {PRECO_MAX} €.")
    return valor


def _criar(args, storage: Storage, chat_id: int) -> dict:
    texto = " ".join(args.texto.split())
    if not texto:
        raise ErroApi("O texto da pesquisa está vazio.")
    if len(texto) > TEXTO_MAX:
        raise ErroApi(f"O texto da pesquisa tem mais de {TEXTO_MAX} caracteres.")
    preco_min, preco_max = _validar_preco(args.preco_min), _validar_preco(args.preco_max)
    if preco_min is not None and preco_max is not None and preco_min > preco_max:
        raise ErroApi("O preço mínimo é maior do que o máximo.")
    url = url_pesquisa(texto, preco_min, preco_max)
    query = parse_search_url(url)
    for existente in storage.list_searches(chat_id=chat_id):
        if existente.domain == query.domain and existente.params == query.params:
            return {"pesquisa": _para_json(existente), "nova": False}
    nome = " ".join((args.nome or "").split()) or texto
    return {"pesquisa": _para_json(storage.add_search(chat_id, nome, url, query)), "nova": True}


def executar(argv: list[str], storage: Storage, chat_id: int | None) -> tuple[int, dict]:
    """(código de saída, JSON). Nunca levanta por causa do pedido: tudo vira {"erro"}."""
    try:
        if chat_id is None:
            raise ErroApi("O ALLOWED_CHAT_ID do VintedBot não está definido.")
        args = _parser().parse_args(argv)
        if args.op == "listar":
            return 0, {"pesquisas": [_para_json(s) for s in storage.list_searches(chat_id=chat_id)]}
        if args.op == "criar":
            return 0, _criar(args, storage, chat_id)
        pesquisa = storage.get_search(args.id)
        if pesquisa is None or pesquisa.chat_id != chat_id:
            raise ErroApi(f"A pesquisa #{args.id} não existe.")
        if args.op == "apagar":
            storage.remove_search(chat_id, args.id)
            return 0, {"pesquisa": _para_json(pesquisa)}
        storage.set_active(chat_id, args.id, args.op == "retomar")
        return 0, {"pesquisa": _para_json(storage.get_search(args.id))}
    except ErroApi as exc:
        return 1, {"erro": str(exc)}


ENV = Path(__file__).resolve().parent.parent / ".env"


def ambiente(herdado: Mapping[str, str], ficheiro: Path) -> dict[str, str]:
    """O ambiente herdado com o .env do bot por cima: quem chama (a Wintermute) tem o seu DB_PATH e o seu token."""
    from dotenv import dotenv_values

    proprio = {k: v for k, v in dotenv_values(ficheiro).items() if v is not None}
    return {**herdado, **proprio}


def main() -> None:
    from vintedbot.config import ConfigError, load_settings

    try:
        settings = load_settings(ambiente(os.environ, ENV))
    except ConfigError as exc:
        codigo, dados = 1, {"erro": str(exc)}
    else:
        storage = Storage(settings.db_path)
        try:
            codigo, dados = executar(sys.argv[1:], storage, settings.allowed_chat_id)
        finally:
            storage.close()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(dados, ensure_ascii=False))
    sys.exit(codigo)


if __name__ == "__main__":
    main()
