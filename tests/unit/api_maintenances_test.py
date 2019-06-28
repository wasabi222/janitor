import pytest
import json

headers = {'content-type' : 'application/json'}

def test_maintenance_root(client, api):
    """
    GIVEN a Flask client and api root
    WHEN the 'maintenances' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get(f'{api}/maintenances')
    assert response.status_code == 200
    assert True


def test_maintenance_read_one(client, api):
    """
    GIVEN a Flask client and api root
    WHEN a valid maintenance is requested by id
    THEN check the response is valid
    """
    resp = client.get(f'{api}/maintenances/1')

    assert resp.status_code == 200

    data = resp.json

    assert data.get('provider_maintenance_id') == 'pmaintid'
    assert 'Eastern' in data.get('timezone')
    assert data.get('cancelled') is False
    assert data.get('rescheduled') is False


def test_maintenance_read_one_bad(client, api):
    """
    GIVEN a Flask client and api root
    WHEN an invalid maintenance is requested by id
    THEN check the response is valid
    """
    resp = client.get(f'{api}/maintenances/9999')

    assert resp.status_code == 404

    data = resp.json

    assert data.get('error') == 404
    assert data.get('message') == 'maintenance not found for id 9999'
