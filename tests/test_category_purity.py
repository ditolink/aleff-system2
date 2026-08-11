"""Pureza das categorias Explorar — show ≠ ensaio, dumps fora, etc."""
from backend.models.database import (
    _belongs_to_theme,
    _is_show_pasta,
    _is_person_essay_pasta,
    _essay_bucket,
    _is_couple_pasta,
    _is_kids_pasta,
    _is_dump_pasta,
)


def test_show_pasta_sonata_not_couple():
    assert _is_show_pasta('SONATA')
    assert _is_show_pasta('sONATA E CRISTINA')
    assert not _is_couple_pasta('sONATA E CRISTINA')


def test_halloween_gameplay_are_ensaios_not_shows():
    assert not _is_show_pasta('Halloween')
    assert not _is_show_pasta('Joãozinho Gameplays')
    assert _is_person_essay_pasta('Halloween')
    assert _is_person_essay_pasta('Joãozinho Gameplays')
    assert _essay_bucket('Halloween') == 'ensaios'
    assert _essay_bucket('Joãozinho Gameplays') == 'ensaios'
    item = {'pasta': 'Halloween', 'categoria': '', 'tags': ''}
    assert _belongs_to_theme(item, 'shows') is False
    assert _belongs_to_theme(item, 'ensaios') is True
    assert _belongs_to_theme(item, 'retratos') is False


def test_barbara_editorial_bucket():
    assert _essay_bucket('Barbara') == 'editorial'
    assert _belongs_to_theme({'pasta': 'Barbara', 'categoria': '', 'tags': ''}, 'editorial')


def test_blocklist_junk_pastas():
    assert not _is_person_essay_pasta('Airsoft')
    assert not _is_person_essay_pasta('logo')
    assert _is_dump_pasta('Site (local)')
    assert not _belongs_to_theme(
        {'pasta': 'Site (local)', 'categoria': 'infantil', 'tags': ''},
        'infantil',
    )


def test_kids_and_couple_basics():
    assert _is_kids_pasta('Sarah 8 Anos')
    assert _is_couple_pasta('Rodrigo e Ana')
    assert _is_couple_pasta('Ana & Elvis')
    assert _belongs_to_theme(
        {'pasta': 'Sarah 8 Anos', 'categoria': '', 'tags': ''},
        'infantil',
    )
    assert _belongs_to_theme(
        {'pasta': 'Rodrigo e Ana', 'categoria': '', 'tags': ''},
        'casais',
    )
