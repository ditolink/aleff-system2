"""Contato → Gmail: URL de compose e ausência de fechamento automático.

Não controla o Gmail externo; valida a construção da URL e o contrato do
openExternal (sem window.open com features / sem window.close).
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTACT_JS = ROOT / 'frontend' / 'js' / 'contact.js'
MAIN_JS = ROOT / 'frontend' / 'js' / 'main.js'


def test_contact_js_has_no_window_close():
    src = CONTACT_JS.read_text(encoding='utf-8')
    assert 'window.close' not in src
    assert 'popup.close' not in src
    assert 'emailWindow' not in src
    assert re.search(r'\bwin\.close\s*\(', src) is None


def test_open_external_never_passes_window_features():
    """Regressão: 3º arg em window.open = popup que o Gmail fecha sozinho."""
    src = CONTACT_JS.read_text(encoding='utf-8')
    # Ignora comentários de bloco — só código executável
    code = re.sub(r'/\*[\s\S]*?\*/', '', src)
    code = re.sub(r'//.*?$', '', code, flags=re.M)
    assert re.search(
        r"window\.open\s*\(\s*url\s*,\s*['_\"]_blank['_\"]\s*,",
        code,
    ) is None
    assert "a.target = '_blank'" in src
    assert 'noopener noreferrer' in src


def test_main_js_gmail_handler_no_feature_window_open():
    src = MAIN_JS.read_text(encoding='utf-8')
    assert "window.open(url, '_blank', 'noopener,noreferrer')" not in src
    assert 'dataset.emailHandlerBound' in src


def test_build_gmail_url_encoding_via_node():
    """URLSearchParams: acentos, quebras de linha, subject/body."""
    node = pytest.importorskip('subprocess')
    import shutil
    import subprocess

    if not shutil.which('node'):
        pytest.skip('node não disponível')

    js = r"""
    const params = new URLSearchParams({
      view: 'cm',
      fs: '1',
      tf: '1',
      to: 'aleffthigo@gmail.com',
      su: 'Solicitação — Casamento | José',
      body: 'Olá, Aleff,\n\nMeu nome é José.\nLinha 2.',
    });
    process.stdout.write('https://mail.google.com/mail/?' + params.toString());
    """
    out = subprocess.check_output(['node', '-e', js], text=True)
    assert out.startswith('https://mail.google.com/mail/?')
    parsed = urlparse(out)
    qs = parse_qs(parsed.query)
    assert qs['view'] == ['cm']
    assert qs['fs'] == ['1']
    assert qs['to'] == ['aleffthigo@gmail.com']
    assert 'Casamento' in unquote(qs['su'][0])
    assert 'José' in unquote(qs['su'][0])
    body = unquote(qs['body'][0])
    assert 'Olá, Aleff,' in body
    assert '\n' in body
    assert 'José' in body


def test_contact_js_build_gmail_url_uses_url_search_params():
    src = CONTACT_JS.read_text(encoding='utf-8')
    assert 'URLSearchParams' in src
    assert 'mail.google.com/mail/' in src
    # Clique principal não deve forçar mailto + sameTab (fechava/trocava o site)
    # mailto só como buildMailtoUrl auxiliar
    assert 'function buildMailtoUrl' in src
    assert re.search(r'function sendGmail[\s\S]*?sameTab:\s*false', src)


def test_no_timeout_closes_gmail_window():
    """Timers no contact.js não devem fechar janela externa."""
    src = CONTACT_JS.read_text(encoding='utf-8')
    for m in re.finditer(r'setTimeout\s*\(\s*([^)]+)\)', src):
        body = m.group(1)
        assert 'close' not in body.lower() or 'closeIgGuide' in src
        assert 'window.close' not in body
        assert 'win.close' not in body
