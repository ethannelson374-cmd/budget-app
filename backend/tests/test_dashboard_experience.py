from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.dashboard_experience import _normalized_cards
from tests.conftest import csrf_headers


def test_dashboard_preferences_persist(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    initial = client.get('/api/v1/dashboard/preferences')
    assert initial.status_code == 200
    payload = initial.json()
    assert payload['preset'] == 'everyday'
    cards = payload['cards']
    assert {card['size'] for card in cards} <= {'compact', 'standard', 'hero'}
    cards[0]['size'] = 'standard'
    cards[-1]['visible'] = False
    update = client.put('/api/v1/dashboard/preferences', json={'cards': cards, 'preset': 'custom'}, headers=csrf_headers(csrf))
    assert update.status_code == 200, update.text
    assert update.json()['cards'][0]['size'] == 'standard'
    assert client.get('/api/v1/dashboard/preferences').json()['cards'] == update.json()['cards']


def test_dashboard_preferences_translate_phase4_sizes() -> None:
    cards = _normalized_cards([
        {'id': 'net_worth', 'size': 'small', 'visible': True},
        {'id': 'cash_flow', 'size': 'wide', 'visible': True},
        {'id': 'accounts', 'size': 'large', 'visible': True},
    ])
    sizes = {card['id']: card['size'] for card in cards}
    assert sizes['net_worth'] == 'compact'
    assert sizes['cash_flow'] == 'hero'
    assert sizes['accounts'] == 'hero'


def test_dashboard_preferences_reject_duplicates(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    response = client.put('/api/v1/dashboard/preferences', json={'preset': 'custom', 'cards': [
        {'id': 'net_worth', 'size': 'compact', 'visible': True}, {'id': 'net_worth', 'size': 'standard', 'visible': True}
    ]}, headers=csrf_headers(csrf))
    assert response.status_code == 422


def test_onboarding_is_real_and_dismissible(authenticated: tuple[TestClient, str]) -> None:
    client, csrf = authenticated
    status = client.get('/api/v1/dashboard/onboarding')
    assert status.status_code == 200
    tasks = {task['key']: task for task in status.json()['tasks']}
    assert tasks['income']['complete'] is True
    assert tasks['account']['complete'] is False
    dismissed = client.post('/api/v1/dashboard/onboarding/dismiss', headers=csrf_headers(csrf))
    assert dismissed.status_code == 200
    assert dismissed.json()['dismissed'] is True
