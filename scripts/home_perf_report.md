# Home Performance Report — Etapa 31

## Antes → depois (resumo)

| Área | Antes | Depois |
|------|--------|--------|
| Grid imgs | `home_ed_*.webp` ~57KB cada, sempre | `srcset` small 320 / medium 800 / local fallback |
| Mobile tipico | ~57KB/tile | ~5–19KB/tile (thumb-small) |
| Lightbox | mesmo arquivo do grid / local | só `thumb-medium` (~800px), prefetch ±1 |
| Originais HD | risco via pool | não usados na Home |
| Fonts Lato | 7 cortes (incl. itálicos) | 3 pesos (300/400/700) |
| Masonry | pack a cada load + MO amplo + scroll fake | coalesce loads, debounce 120ms, só childList |
| Badges nº | `backdrop-filter: blur` em cada tile | ocultos na vitrine editorial |
| Filtro mobile | grayscale 42% + transition longa | mais leve no ≤768px |
| nginx | já tinha cache thumbs + `/fotos` | mantido / documentado |

## Checklist

- [x] primeira tela: hero eager + fetchpriority high
- [x] primeiras 2 do capítulo: eager; resto lazy
- [x] srcset + sizes
- [x] aspect-ratio nos tiles (3:4 / 3:2) → CLS controlado
- [x] sem preload da galeria inteira
- [x] lightbox sob demanda + vizinhos
- [x] vídeos `preload="none"` + poster
- [x] IA só offline (`photo_curator`)
- [x] cache nginx thumbs / fotos (setup-oracle.sh)
- [x] prefers-reduced-motion respeitado no filtro

## Como medir

Chrome DevTools → Lighthouse (Mobile + Desktop) e Network throttle “Fast 3G”:

- LCP ≈ hero silhueta
- CLS ≈ 0 (frames com aspect-ratio)
- pedidos iniciais: hero + 1–2 tiles (small/medium), não 13 originais

## Comandos

```bash
# regenerar thumbs small/medium dos IDs da Home (já feito no apply)
python -m backend.services.photo_curator --skip-analyze --apply
```

Hard refresh: `?v=20260810perf`
