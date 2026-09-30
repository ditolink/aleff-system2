"""Testes para suporte híbrido do OpenCLIP + Hugging Face Serverless API."""
import os
from unittest.mock import MagicMock, patch
import pytest

from backend.services import clip_tagger


def test_clip_enabled_with_hf_token(monkeypatch):
    monkeypatch.setenv('CLIP_ENABLED', 'false')
    monkeypatch.setenv('HF_API_TOKEN', 'hf_test_mock_token_123')
    
    assert clip_tagger.is_enabled() is True
    assert clip_tagger.is_ready() is True
    
    info = clip_tagger.get_model_info()
    assert info['hf_api_configured'] is True


def test_hf_encode_text_mocked(monkeypatch):
    monkeypatch.setenv('HF_API_TOKEN', 'hf_test_mock_token_123')
    
    # Mock requests response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [0.1] * 512
    
    with patch.object(clip_tagger._requests_session, 'post', return_value=mock_resp):
        vec = clip_tagger._hf_encode_text('casamento na praia')
        assert vec is not None
        assert len(vec) == 512


def test_hf_generate_tags_mocked(monkeypatch):
    from PIL import Image
    monkeypatch.setenv('HF_API_TOKEN', 'hf_test_mock_token_123')
    
    # Mock requests response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {'label': 'wedding', 'score': 0.88},
        {'label': 'beach', 'score': 0.75}
    ]
    
    test_img = Image.new('RGB', (100, 100), color='blue')
    
    with patch.object(clip_tagger._requests_session, 'post', return_value=mock_resp):
        res = clip_tagger._hf_generate_tags(test_img, top_k=5, threshold=0.1)
        assert res is not None
        assert res['status'] == 'ok'
        assert 'casamento' in res['tags']
        assert 'praia' in res['tags']
