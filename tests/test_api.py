from vintedbot.api import executar, url_pesquisa
from vintedbot.storage import Storage
from vintedbot.vinted.url_parser import parse_search_url

CHAT = 42


def _criar(storage, *args):
    return executar(["criar", *args], storage, CHAT)


def test_url_pesquisa():
    url = url_pesquisa("Kirby Switch 2", None, 40)
    assert url == "https://www.vinted.pt/catalog?search_text=Kirby+Switch+2&price_to=40&currency=EUR&order=newest_first"
    assert parse_search_url(url).params["search_text"] == "Kirby Switch 2"
    assert url_pesquisa("x", 10.5, None) == (
        "https://www.vinted.pt/catalog?search_text=x&price_from=10.5&currency=EUR&order=newest_first"
    )


def test_criar_e_listar():
    storage = Storage()
    codigo, dados = _criar(storage, "--texto=Kirby", "--preco-max=40")
    assert codigo == 0 and dados["nova"] is True
    assert dados["pesquisa"] == {
        "id": 1, "nome": "Kirby", "ativa": True, "texto": "Kirby", "preco_min": None, "preco_max": 40,
        "url": url_pesquisa("Kirby", None, 40),
    }  # fmt: skip
    search = storage.get_search(1)
    assert search.chat_id == CHAT and not search.primed  # o Monitor faz o priming: nada de alertas antigos
    assert executar(["listar"], storage, CHAT) == (0, {"pesquisas": [dados["pesquisa"]]})


def test_criar_com_nome_e_precos():
    storage = Storage()
    codigo, dados = _criar(storage, "--texto=Octopath", "--preco-min=10", "--preco-max=30.5", "--nome=Octopath barato")
    assert codigo == 0
    assert (dados["pesquisa"]["nome"], dados["pesquisa"]["preco_min"], dados["pesquisa"]["preco_max"]) == (
        "Octopath barato", 10, 30.5
    )


def test_criar_repetida_nao_duplica():
    storage = Storage()
    _criar(storage, "--texto=Kirby", "--preco-max=40")
    codigo, dados = _criar(storage, "--texto=Kirby", "--preco-max=40", "--nome=outro")
    assert codigo == 0 and dados["nova"] is False and dados["pesquisa"]["id"] == 1
    assert len(storage.list_searches()) == 1
    assert _criar(storage, "--texto=Kirby", "--preco-max=50")[1]["nova"] is True


def test_pausar_retomar_apagar():
    storage = Storage()
    _criar(storage, "--texto=Kirby")
    codigo, dados = executar(["pausar", "--id=1"], storage, CHAT)
    assert codigo == 0 and dados["pesquisa"]["ativa"] is False
    assert executar(["retomar", "--id=1"], storage, CHAT)[1]["pesquisa"]["ativa"] is True
    codigo, dados = executar(["apagar", "--id=1"], storage, CHAT)
    assert codigo == 0 and dados["pesquisa"]["nome"] == "Kirby"
    assert storage.list_searches() == []


def test_id_inexistente():
    storage = Storage()
    for op in ("pausar", "retomar", "apagar"):
        assert executar([op, "--id=9"], storage, CHAT) == (1, {"erro": "A pesquisa #9 não existe."})


def test_outro_chat_nao_se_ve():
    storage = Storage()
    _criar(storage, "--texto=Kirby")
    assert executar(["apagar", "--id=1"], storage, 7) == (1, {"erro": "A pesquisa #1 não existe."})
    assert executar(["listar"], storage, 7) == (0, {"pesquisas": []})


def test_validacao():
    storage = Storage()
    for args, erro in [
        (["--texto=  "], "O texto da pesquisa está vazio."),
        (["--texto=" + "x" * 101], "O texto da pesquisa tem mais de 100 caracteres."),
        (["--texto=x", "--preco-max=-1"], "Os preços têm de estar entre 0 e 10000 €."),
        (["--texto=x", "--preco-max=abc"], "Os preços têm de ser números."),
        (["--texto=x", "--preco-min=50", "--preco-max=10"], "O preço mínimo é maior do que o máximo."),
    ]:
        assert _criar(storage, *args) == (1, {"erro": erro}), args
    assert executar(["inventado"], storage, CHAT)[0] == 1
    assert executar(["pausar"], storage, CHAT)[0] == 1
    assert storage.list_searches() == []


def test_sem_chat_id():
    assert executar(["listar"], Storage(), None) == (1, {"erro": "O ALLOWED_CHAT_ID do VintedBot não está definido."})


def test_texto_com_aspas_e_japones():
    storage = Storage()
    codigo, dados = _criar(storage, '--texto=カービィ "deluxe"')
    assert codigo == 0 and dados["pesquisa"]["texto"] == 'カービィ "deluxe"'


def test_texto_a_comecar_por_hifen():
    storage = Storage()
    codigo, dados = _criar(storage, "--texto=-50% kirby")
    assert codigo == 0 and dados["pesquisa"]["texto"] == "-50% kirby"
