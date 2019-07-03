import pytest
import json

headers = {'content-type': 'application/json'}


def test_circuit_root(client, api):
    """
    GIVEN a Flask client and api root
    WHEN the 'circuit' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get(f'{api}/circuits')
    assert response.status_code == 200
    assert True


def test_circuit_add(client, api):
    """
    GIVEN a Flask client and api root
    WHEN the 'circuit' api root is posted to
    THEN check the circuit was created
    """
    data = {'a_side': 'a', 'z_side': 'z', 'provider_cid': '123', 'provider_id': 1}
    data = json.dumps(data)
    resp = client.post(f'{api}/circuits', data=data, headers=headers)

    assert resp.status_code == 201


def test_circuit_add_bad_one(client, api):
    """
    GIVEN a Flask client and api root
    WHEN an invalid circuit is attempted to be created with a dup cid
    THEN check the circuit was not created
    """
    data = {'a_side': 'a', 'z_side': 'z', 'provider_cid': 'xxx', 'provider_id': 1}
    data = json.dumps(data)
    resp = client.post(f'{api}/circuits', data=data, headers=headers)

    assert resp.status_code == 409


def test_circuit_add_bad_two(client, api):
    """
    GIVEN a Flask client and api root
    WHEN an invalid circuit is attempted to be created with an invalid provider
    THEN check the circuit was not created
    """
    data = {'a_side': 'a', 'z_side': 'z', 'provider_cid': 'abc', 'provider_id': 111111}
    data = json.dumps(data)
    resp = client.post(f'{api}/circuits', data=data, headers=headers)

    assert resp.status_code == 403


def test_circuit_read_one(client, api):
    """
    GIVEN a Flask client and api root
    WHEN a valid circuit is requested by id
    THEN check the circuit was returned
    """
    resp = client.get(f'{api}/circuits/1')

    assert resp.status_code == 200

    data = resp.json

    assert data.get('provider_id') is not None
    assert data.get('provider_cid') == 'xxx'
    assert data.get('a_side') == 'a'
    assert data.get('z_side') == 'z'


def test_circuit_read_one_bad(client, api):
    """
    GIVEN a Flask client and api root
    WHEN an invalid circuit is requested by id
    THEN check the circuit was returned
    """
    resp = client.get(f'{api}/circuits/9999')

    assert resp.status_code == 404

    data = resp.json

    assert data.get('error') == 404
    assert data.get('message') == 'circuit not found for id 9999'
