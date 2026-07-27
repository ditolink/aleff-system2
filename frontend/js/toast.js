/* =====================================================
   TOAST — sistema de notificações reutilizável
   Uso: Toast.success('Título', 'mensagem opcional')
        Toast.error('Título', 'mensagem opcional')
        Toast.warning('Título', 'mensagem opcional')
        Toast.info('Título', 'mensagem opcional')
===================================================== */
const Toast = (() => {
  let stack = null;

  function ensureStack() {
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      document.body.appendChild(stack);
    }
    return stack;
  }

  const ICONS = {
    success: '✓',
    error:   '✕',
    warning: '⚠',
    info:    'i'
  };

  function show(type, title, message = '', duration = 5000) {
    const container = ensureStack();

    const card = document.createElement('div');
    card.className = `toast-card ${type}`;
    card.innerHTML = `
      <span class="toast-icon">${ICONS[type] || ICONS.info}</span>
      <div class="toast-body">
        <p class="toast-title">${esc(title)}</p>
        ${message ? `<p class="toast-msg">${esc(message)}</p>` : ''}
      </div>
      <button class="toast-close" aria-label="Fechar">✕</button>
    `;

    container.appendChild(card);
    requestAnimationFrame(() => requestAnimationFrame(() => card.classList.add('in')));

    let removed = false;
    const remove = () => {
      if (removed) return;
      removed = true;
      card.classList.remove('in');
      card.classList.add('out');
      setTimeout(() => card.remove(), 350);
    };

    card.querySelector('.toast-close').addEventListener('click', remove);

    if (duration > 0) {
      setTimeout(remove, duration);
    }

    return remove;
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  return {
    success: (title, msg, dur) => show('success', title, msg, dur),
    error:   (title, msg, dur) => show('error',   title, msg, dur ?? 7000),
    warning: (title, msg, dur) => show('warning', title, msg, dur),
    info:    (title, msg, dur) => show('info',    title, msg, dur),
  };
})();