"""Gera thumbs panorâmicos de capa pra grade Explorar."""
from backend.models.database import pick_category_covers, CATEGORY_COVER_OVERRIDES
from backend.services import thumb_pipeline as tp

explore = {
    'shows': ('show', 'shows', 'palco', 'banda', 'concerto', 'artista'),
    'casamento': ('casamento', 'noiva', 'noivo', 'cerimonia', 'igreja', 'alianca', 'vestido'),
    'retratos': ('retrato', 'retratos', 'close', 'estudio', 'olhar'),
    'casais': ('casal', 'casais', 'romantico', 'amor', 'beijo', 'abraco'),
    'familia': ('familia', 'familiar', 'geracoes'),
    'infantil': ('infantil', 'crianca', 'bebe', 'aniversario'),
    'ensaios': ('ensaio', 'ensaios', 'externo', 'sessao', 'lifestyle'),
    'editorial': ('editorial', 'moda', 'fashion', 'conceito', 'artistico'),
}

covers = pick_category_covers(explore, thumb_size=560)
for cat, c in covers.items():
    mid = c.get('id')
    ready = False
    if mid:
        p = tp.thumb_path(int(mid), tp.TIER_COVER)
        ready = p.is_file() and p.stat().st_size > 80
    print(
        f'{cat:12} id={mid} pasta={c.get("pasta")!r} '
        f'url={c.get("thumb_url")} ready={ready}'
    )
print('override editorial', CATEGORY_COVER_OVERRIDES)
