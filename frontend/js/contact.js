/* ============================================================
   contact.js — Contato / envio (WhatsApp, Gmail, Instagram)
   Meta: Instagram NÃO permite pré-preencher Direct (?text=).
   Fluxo: copiar → modal guia → Abrir Direct (depois do clique).
============================================================ */
const ContactSend = (() => {
  const IG = {
    username: 'aleffthiagofilms',
    profileUrl: 'https://www.instagram.com/aleffthiagofilms/',
    /** Link oficial Meta para abrir o Direct (sem texto pré-preenchido) */
    dmUrl: 'https://ig.me/m/aleffthiagofilms',
  };

  function isMobile() {
    return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
      || (navigator.maxTouchPoints > 1 && /Mac/.test(navigator.platform || ''));
  }

  async function copyToClipboard(texto) {
    const value = String(texto || '');
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (_) {
      try {
        const area = document.createElement('textarea');
        area.value = value;
        area.setAttribute('readonly', '');
        area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
        document.body.appendChild(area);
        area.select();
        const ok = document.execCommand('copy');
        area.remove();
        return ok;
      } catch (_) {
        return false;
      }
    }
  }

  function openExternal(url, { sameTab = false } = {}) {
    if (!url) return null;
    if (sameTab) {
      window.location.assign(url);
      return window;
    }
    const win = window.open(url, '_blank', 'noopener,noreferrer');
    if (win) return win;
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 500);
    return null;
  }

  /** Mensagens por canal — tom certo pra cada plataforma */
  function buildStudioMessage(fields = {}, channel = 'whatsapp') {
    const ch = String(channel || 'whatsapp').toLowerCase();
    if (ch === 'gmail' || ch === 'email') return buildGmailMessage(fields);
    if (ch === 'instagram') return buildDirectMessage(fields);
    return buildChatMessage(fields);
  }

  /** WhatsApp — direto, curto, conversacional */
  function buildChatMessage({ nome = '', contato = '', tipo = '', mensagem = '' } = {}) {
    const lines = [
      'Olá, Aleff!',
      '',
      'Vi seu portfólio e gostaria de conversar sobre um projeto.',
    ];
    if (nome) lines.push('', 'Meu nome:', nome);
    if (contato) lines.push('', 'Meu contato:', contato);
    if (tipo) lines.push('', 'Projeto:', tipo);
    if (mensagem) lines.push('', 'Mensagem:', mensagem);
    lines.push('', 'Obrigado!');
    return lines.join('\n');
  }

  /** Instagram Direct — clara e fácil de colar */
  function buildDirectMessage(fields = {}) {
    return buildChatMessage(fields);
  }

  /** Gmail — e-mail formal de estúdio */
  function buildGmailMessage({ nome = '', contato = '', tipo = '', mensagem = '' } = {}) {
    const lines = [];

    lines.push('Olá, Aleff,');
    lines.push('');

    if (nome) {
      lines.push(
        `Meu nome é ${nome}. Conheci seu trabalho pelo portfólio e gostaria de alinhar um projeto` +
        (tipo ? ` de ${tipo.toLowerCase()}` : '') +
        '.'
      );
    } else {
      lines.push(
        'Conheci seu trabalho pelo portfólio e gostaria de alinhar um projeto' +
        (tipo ? ` de ${tipo.toLowerCase()}` : '') +
        '.'
      );
    }

    lines.push('');
    lines.push(
      'Busco alguém com olhar cinematográfico e entrega cuidadosa — e o seu acervo me passou exatamente essa referência.'
    );

    if (mensagem) {
      lines.push('');
      lines.push('Sobre o que preciso:');
      lines.push(mensagem);
    }

    lines.push('');
    lines.push('Dados para retorno');
    lines.push('────────────────');
    lines.push(`Nome: ${nome || '—'}`);
    lines.push(`Contato: ${contato || '—'}`);
    lines.push(`Tipo de projeto: ${tipo || '—'}`);
    lines.push('Origem: Portfólio — aleffthiago');

    lines.push('');
    lines.push(
      'Fico à disposição para combinarmos data, local, formato (foto / vídeo / ambos) e demais detalhes.'
    );
    lines.push('');
    lines.push('Atenciosamente,');
    lines.push(nome || 'Aguardando retorno');

    return lines.join('\n');
  }

  /** Assunto profissional pro Gmail */
  function buildGmailSubject({ nome = '', tipo = '' } = {}) {
    if (tipo && nome) return `Solicitação de orçamento — ${tipo} | ${nome}`;
    if (tipo) return `Solicitação de orçamento — ${tipo}`;
    if (nome) return `Contato via portfólio — ${nome}`;
    return 'Contato via portfólio — Aleff Thiago';
  }

  /* ── Flash “✓ Mensagem copiada” no bloco Mensagem pronta ── */
  let flashTimer = null;

  function showCopyFlash(root, { sub = 'Cole no Direct do Instagram.' } = {}) {
    if (!root) return;
    let flash = root.querySelector('.msg-pronta-flash');
    if (!flash) {
      flash = document.createElement('div');
      flash.className = 'msg-pronta-flash';
      flash.setAttribute('aria-live', 'polite');
      flash.innerHTML = `
        <span class="msg-pronta-flash-check" aria-hidden="true">✓</span>
        <span class="msg-pronta-flash-title">Mensagem copiada</span>
        <span class="msg-pronta-flash-sub"></span>
      `;
      root.appendChild(flash);
    }
    const subEl = flash.querySelector('.msg-pronta-flash-sub');
    if (subEl) subEl.textContent = sub;
    flash.classList.remove('is-out');
    flash.classList.add('is-on');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      flash.classList.add('is-out');
      setTimeout(() => flash.classList.remove('is-on', 'is-out'), 420);
    }, 2000);
  }

  /* ── Modal guia Instagram ──────────────────────────────── */
  let pendingOpenUrl = null;
  let lastCopied = '';

  function ensureIgGuide() {
    let el = document.getElementById('igGuide');
    if (el && !el.querySelector('#igGuideOpen')) {
      el.remove();
      el = null;
    }
    if (el) return el;

    el = document.createElement('div');
    el.id = 'igGuide';
    el.className = 'ig-guide';
    el.hidden = true;
    el.innerHTML = `
      <div class="ig-guide-bg" data-ig-dismiss="1"></div>
      <div class="ig-guide-card" role="dialog" aria-modal="true" aria-labelledby="igGuideTitle">
        <div class="ig-guide-mark" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
            <rect x="2" y="2" width="20" height="20" rx="5"/>
            <circle cx="12" cy="12" r="4"/>
            <circle cx="17.5" cy="6.5" r="1.2" fill="currentColor" stroke="none"/>
          </svg>
        </div>
        <p class="ig-guide-kicker">Instagram</p>
        <h3 class="ig-guide-title" id="igGuideTitle">Mensagem pronta</h3>
        <p class="ig-guide-body" id="igGuideBody"></p>
        <p class="ig-guide-note">O Instagram não permite abrir o Direct com texto preenchido — por isso a gente copia por você.</p>
        <div class="ig-guide-actions">
          <button type="button" class="ig-guide-primary" id="igGuideOpen">Abrir Direct</button>
          <button type="button" class="ig-guide-secondary" id="igGuideRecopy">Copiar de novo</button>
        </div>
      </div>
    `;
    document.body.appendChild(el);

    el.addEventListener('click', (e) => {
      if (e.target.closest('[data-ig-dismiss]')) {
        pendingOpenUrl = null;
        closeIgGuide();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !el.hidden) {
        pendingOpenUrl = null;
        closeIgGuide();
      }
    });
    return el;
  }

  function openIgGuide({ copied = true, onRecopy, openUrl = null } = {}) {
    const el = ensureIgGuide();
    const body = el.querySelector('#igGuideBody');
    const mobile = isMobile();
    pendingOpenUrl = openUrl || null;

    if (body) {
      if (!copied) {
        body.textContent = mobile
          ? 'Não foi possível copiar automaticamente. Depois de abrir o Direct, digite a mensagem do preview.'
          : 'Não foi possível copiar automaticamente. Selecione o texto em Mensagem pronta e use Ctrl+C.';
      } else if (mobile) {
        body.textContent = 'A mensagem já foi copiada.\n\nToque em Abrir Direct, depois toque e segure na caixa de texto e escolha Colar.';
      } else {
        body.textContent = 'A mensagem já foi copiada.\n\nClique em Abrir Direct e, no Instagram, pressione Ctrl+V.';
      }
    }

    const openBtn = el.querySelector('#igGuideOpen');
    if (openBtn) {
      openBtn.textContent = 'Abrir Direct';
      openBtn.onclick = () => {
        const url = pendingOpenUrl || IG.dmUrl;
        pendingOpenUrl = null;
        closeIgGuide();
        // Abre só depois do usuário confirmar o modal
        openExternal(url, { sameTab: isMobile() });
      };
    }

    const recopy = el.querySelector('#igGuideRecopy');
    if (recopy) {
      recopy.onclick = async () => {
        const ok = await copyToClipboard(lastCopied);
        if (typeof onRecopy === 'function') onRecopy(ok);
        if (ok) {
          recopy.textContent = 'Copiado ✓';
          setTimeout(() => { recopy.textContent = 'Copiar de novo'; }, 1600);
        }
      };
    }

    el.hidden = false;
    requestAnimationFrame(() => el.classList.add('is-open'));
    document.body.classList.add('ig-guide-open');
  }

  function closeIgGuide() {
    const el = document.getElementById('igGuide');
    if (!el) return;
    el.classList.remove('is-open');
    document.body.classList.remove('ig-guide-open');
    setTimeout(() => { el.hidden = true; }, 320);
  }

  /** Instagram — igual Gmail/WhatsApp: abre o Direct na hora (sem copiar / sem modal). */
  function buildInstagramUrl(texto) {
    const body = encodeURIComponent(String(texto || ''));
    // ig.me abre o Direct; text= é melhor esforço (a Meta costuma ignorar no app)
    return `https://ig.me/m/${IG.username}?text=${body}`;
  }

  function sendInstagram(texto) {
    const url = buildInstagramUrl(texto);
    const opened = openExternal(url, { sameTab: isMobile() });
    return { url, opened: !!opened };
  }

  /** Gmail — igual WhatsApp: abre compose já com a mensagem preenchida (sem copiar). */
  function buildGmailUrl(
    texto,
    { subject = 'Contato via portfólio — Aleff Thiago', to = 'aleffthigo@gmail.com' } = {}
  ) {
    const subjectEnc = encodeURIComponent(subject);
    const bodyEnc = encodeURIComponent(String(texto || ''));
    const toEnc = encodeURIComponent(to);
    if (isMobile()) {
      return `mailto:${to}?subject=${subjectEnc}&body=${bodyEnc}`;
    }
    return `https://mail.google.com/mail/?view=cm&fs=1&tf=1&to=${toEnc}&su=${subjectEnc}&body=${bodyEnc}`;
  }

  function sendGmail(texto, opts = {}) {
    const url = buildGmailUrl(texto, opts);
    const opened = openExternal(url, { sameTab: isMobile() });
    return { url, opened: !!opened };
  }

  return {
    IG,
    isMobile,
    copyToClipboard,
    openExternal,
    buildStudioMessage,
    buildGmailMessage,
    buildGmailSubject,
    buildChatMessage,
    showCopyFlash,
    openIgGuide,
    closeIgGuide,
    buildInstagramUrl,
    sendInstagram,
    buildGmailUrl,
    sendGmail,
  };
})();
