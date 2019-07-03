import pytest
import json

headers = {'content-type': 'application/json'}


def test_provider_root(client, api):
    """
    GIVEN a Flask client and api root
    WHEN the 'providers' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get(f'{api}/providers')
    assert response.status_code == 200


def test_providers_read_one(client, api):
    """
    GIVEN a Flask client and api root
    WHEN a valid provider is requested by id
    THEN check the response is valid
    """
    resp = client.get(f'{api}/providers/1')

    assert resp.status_code == 200

    data = resp.json

    assert data.get('name') == 'zayo'
    assert data.get('type') == 'backbone'
    assert data.get('email_esc') == 'mr@zayo.com'


def test_providers_bad_read_one(client, api):
    """
    GIVEN a Flask client and api root
    WHEN an invalid provider is requested by id
    THEN check the response is valid
    """
    resp = client.get(f'{api}/providers/99999')

    assert resp.status_code == 404
