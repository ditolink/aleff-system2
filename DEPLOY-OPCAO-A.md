# Guia de Deploy 100% Gratuito (Opção A)
## Cloudflare Pages (Frontend) + Render (Backend Leve) + Hugging Face (IA)

Esta arquitetura foi projetada para rodar **24 horas por dia na nuvem, 100% gratuita, sem cartão de crédito e sem estourar os limites de 512MB de memória**.

---

### PARTE 1: Frontend no Cloudflare Pages (Site Ultrarrápido)

1. Acesse o painel da Cloudflare: [https://dash.cloudflare.com/](https://dash.cloudflare.com/)
2. No menu lateral, vá em **Workers & Pages** → clique em **Create application**.
3. Selecione a aba **Pages** e clique em **Connect to Git**.
4. Selecione o repositório `ditolink/aleff-system2`.
5. Preencha as configurações de build:
   - **Project name:** `aleff-portfolio` (ou o nome que preferir)
   - **Production branch:** `main`
   - **Root directory (advanced):** `frontend`
   - **Framework preset:** `None`
   - **Build command:** *(deixe em branco)*
   - **Build output directory:** `.`
6. Clique em **Save and Deploy**.
7. O Cloudflare Pages vai publicar seu site com uma URL gratuita (ex: `aleff-portfolio.pages.dev`).

> A raiz precisa ser `frontend` para que o Cloudflare encontre `frontend/functions/api/[[path]].js`. Sem essa Function, a API do site nao sera encaminhada corretamente.

#### Configurar seu dominio `aleffthiago.com.br` no Cloudflare Pages:
1. Dentro do seu projeto no Cloudflare Pages, vá na aba **Custom domains** → **Set up a custom domain**.
2. Digite `aleffthiago.com.br` e siga as instrucoes para apontar o dominio no Cloudflare. Se o DNS ainda estiver no Registro.br, altere os nameservers para os informados pela Cloudflare.

---

### PARTE 2: Backend Leve no Render (API & Google Drive)

1. Acesse o Render: [https://render.com/](https://render.com/) e faça login com seu GitHub.
2. Clique em **New +** → **Blueprint**.
3. Conecte o repositório `ditolink/aleff-system2`.
4. O Render vai ler automaticamente o arquivo `render.yaml` que já deixamos configurado com o `Dockerfile.lite` (que consome apenas ~80MB de RAM).
5. Preencha as variáveis de ambiente secretas:
   - `DRIVE_FOLDER_ID`: O ID da pasta do Google Drive com as fotos.
   - `GOOGLE_APPLICATION_CREDENTIALS`: O JSON da sua Service Account do Google.
   - `AUTH_USERS`: Usuários e senhas de login (ex: `aleff:SUA_SENHA:admin`).
   - `HF_API_TOKEN`: Seu token gratuito da Hugging Face.
6. Clique em **Apply**. O backend estará online com uma URL tipo `https://aleff-backend.onrender.com`.

> O plano gratuito do Render suspende o servico apos 15 minutos sem trafego; a primeira requisicao depois disso pode levar cerca de um minuto. O filesystem e efemero: SQLite, uploads e caches locais podem ser apagados ao reiniciar ou suspender o servico. As fotos no Drive continuam no Drive, mas os dados locais do banco precisam ser reconstruidos ou migrados para armazenamento persistente antes de depender deles.

---

### PARTE 3: Conectar o Frontend ao Backend

1. Volte ao painel do seu projeto no **Cloudflare Pages**.
2. Va em **Settings** → **Variables and Secrets**.
3. Adicione a variável:
   - **Variable name:** `BACKEND_URL`
   - **Value:** A URL do seu backend no Render (ex: `https://aleff-backend.onrender.com`).
4. Salve a variavel nos ambientes **Production** e **Preview**, conforme necessario, e faca um novo deploy para ela entrar em vigor.
5. Pronto! Todas as chamadas para `/api/*` serão direcionadas de forma invisível e ultrarrápida para o seu backend.

---

### PARTE 4: Como ativar as IAs gratuitas na Nuvem (Hugging Face)

1. Crie uma conta gratuita em: [https://huggingface.co/join](https://huggingface.co/join) (sem cartão).
2. Vá em [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
3. Clique em **New token** → tipo **Read** → dê o nome de `portfolio` e copie o token gerado.
4. Crie um token com permissao para chamar **Inference Providers** e adicione-o como `HF_API_TOKEN` no painel do Render. Mantenha o token como segredo e nunca o coloque no frontend ou no Git.
5. O token permite que o backend tente usar a inferencia remota, sem carregar o OpenCLIP localmente. A disponibilidade, os modelos servidos e a cota gratuita dependem da Hugging Face; valide uma chamada real de tags depois do deploy. Os testes automatizados mockam a API e nao comprovam que os endpoints/modelos configurados continuam ativos.

---

### Checklist depois do deploy

1. Abra `https://aleff-portfolio.pages.dev` e confirme que o site carrega.
2. Abra `https://aleff-portfolio.pages.dev/api/ai/status` e confirme que a resposta JSON vem do backend Render.
3. Confira o status do Google Drive no painel da aplicacao e teste login, busca e carregamento de uma foto; teste tambem apos o Render ficar ocioso para observar o cold start.
4. Confira os logs de deploy e runtime nos paineis Cloudflare e Render. Nao publique credenciais do Google, `AUTH_USERS` ou tokens em logs, screenshots ou no repositorio.
