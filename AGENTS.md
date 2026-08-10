# AGENTS.md — Padrão obrigatório para qualquer agente / modelo

Este arquivo é a **fonte de verdade** de processo no `aleff-system2`.
Qualquer agente (Cursor, Claude, GPT, Codex, etc.) **deve** seguir estas regras.

---

## 1. Issues → Branch → PR → Deploy

### Toda tarefa vira Issue

Antes de implementar **Correção**, **Melhoria** ou **Nova função**:

1. Crie uma Issue no GitHub (`gh issue create`) com um destes labels:
   - `tipo:correcao` — bug / regressão
   - `tipo:melhoria` — UX, performance, polish
   - `tipo:feature` — funcionalidade nova
   - Extras úteis: `area:frontend`, `area:backend`, `area:devops`, `area:motion`, `area:obs`, `area:qa`
2. Título curto e acionável (ex.: `fix: Gmail fecha ao abrir compose`).
3. Corpo com: contexto, critério de aceite, arquivos provavelmente tocados.

### Trabalho só via Pull Request

1. Crie branch a partir de `main` (ou base acordada):
   - `fix/<issue>-descricao-curta`
   - `melhoria/<issue>-descricao-curta`
   - `feat/<issue>-descricao-curta`
2. Commits pequenos e claros.
3. Abra PR com `gh pr create`.
4. **Mencione a Issue na descrição do PR** (obrigatório):
   - `Fixes #123` (fecha ao merge) ou `Refs #123` / `Closes #123`.
5. Deploy / merge só depois do PR aprovado (CI verde quando existir).

### Template mínimo de PR

```markdown
## Summary
- …

## Issue
Fixes #<N>

## Test plan
- [ ] …
```

### O que NÃO fazer

- Não mergear direto em `main` sem PR (exceto hotfixes de emergência documentados).
- Não implementar tarefa grande sem Issue.
- Não abrir PR sem referência à Issue.

---

## 2. Motion / UI (Design Motion Principles)

Base: [kylezantos/design-motion-principles](https://github.com/kylezantos/design-motion-principles).

Para este portfólio (site criativo + painel admin):

- Lente primária: **Jhey Tompkins** (presença criativa, CSS intencional).
- Lente secundária: **Jakub Krehel** (polish de produto).
- Evitar slop: pulse infinito genérico, hover-scale em tudo, stagger excessivo, blur-everywhere.

### Obrigatório em toda interface

| Requisito | Como |
|-----------|------|
| Skeleton | Estados de loading com placeholders (`.skel`, grids) |
| Lazy loading | `loading="lazy"` / `decoding="async"` em mídia below-fold |
| Entrada | Animação curta (`.motion-enter`, ~200–400ms) |
| Saída | Transição ao fechar modal/lightbox/toast |
| Carregamento | Feedback visual (progress bar, cam hint, disabled CTA) |
| Progresso | Barras / % / página X de Y em listas longas |
| Acessibilidade | Respeitar `prefers-reduced-motion` |

CSS compartilhado: `frontend/css/motion.css`.

---

## 3. Observabilidade, qualidade e testes

### Observabilidade (stack alvo)

- **OpenTelemetry** — traces/metrics base (Python Flask).
- **Sentry** — erros backend + opcional frontend.
- Datadog / New Relic — opcionais via OTLP export (não hardcode vendor).

Env: ver `.env.example` (`SENTRY_DSN`, `OTEL_*`).

### Qualidade / lint

| Camada | Ferramenta |
|--------|------------|
| Python | Ruff (+ opcional Arch contract / pylint) |
| JS/CSS | Biome |
| Dead code | Knip (quando houver package.json de tooling) |
| Mutation (opcional) | Stryker / mutmut |

### Testes

| Tipo | Ferramenta |
|------|------------|
| Unit / integração | pytest + coverage → Codecov |
| E2E | Playwright |

Rodar local:

```bash
pytest -q --cov=backend --cov-report=xml
npx playwright test
```

CI: `.github/workflows/ci.yml`.

---

## 4. Checklist rápido do agente

Antes de codar:

- [ ] Issue criada / referenciada
- [ ] Branch nomeada com o número da Issue

Ao abrir PR:

- [ ] `Fixes #N` ou `Refs #N` no body
- [ ] Motion: skeleton / lazy / enter-exit onde couber
- [ ] Sem secrets no commit
- [ ] Testes ou plano de teste no PR

---

## 5. Áreas do produto (orientação)

- `frontend/` — portfólio público, busca, admin UI
- `backend/` — Flask API, Drive, busca, CLIP/face
- `deploy/` — Oracle / Railway
- Issues de curadoria de fotos do cliente → `tipo:melhoria` + `area:frontend`
