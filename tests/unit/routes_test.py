import pytest


def test_index_page(client):
    """
    GIVEN a Flask application
    WHEN the '/' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/')
    assert response.status_code == 200


def test_index_page_post(client):
    """
    GIVEN a Flask application
    WHEN the '/' page is POSTed to
    THEN check the response is valid
    """
    client.application.apscheduler.start()
    response = client.post('/')
    client.application.apscheduler.shutdown()
    assert response.status_code == 302


def test_providers_page(client):
    """
    GIVEN a Flask application
    WHEN the '/providers' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/providers')
    assert response.status_code == 200
    assert b'<table class="table table-hover" id="providers">' in response.data


def test_providers_details_page(client):
    """
    GIVEN a Flask application
    WHEN the '/providers/1' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/providers/1')
    assert response.status_code == 200


def test_circuits_page(client):
    """
    GIVEN a Flask application
    WHEN the '/circuits' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/circuits')
    assert response.status_code == 200
    assert b'<table class="table table-hover" id="circuits">' in response.data


def test_circuits_details_page(client):
    """
    GIVEN a Flask application
    WHEN the '/circuits/1' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/circuits/1')
    assert response.status_code == 200


def test_circuits_page_form(client):
    """
    GIVEN a Flask application
    WHEN the '/circuits' page is POSTed to
    THEN check the response is valid and the circuit was created
    """
    data = {'provider_cid': 'fake cid', 'provider': 1}
    response = client.post('/circuits', data=data)
    assert response.status_code == 200
    assert b'<table class="table table-hover" id="circuits">' in response.data
    assert b'fake cid' in response.data


def test_maintenances_page(client):
    """
    GIVEN a Flask application
    WHEN the '/' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/maintenances')
    assert response.status_code == 200
    assert b'<table class="table table-hover" id="maintenances">' in response.data


def test_maintenances_detail_page(client):
    """
    GIVEN a Flask application
    WHEN the '/maintenances/1' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/maintenances/1')
    assert response.status_code == 200


def test_metrics_page(client):
    """
    GIVEN a Flask application
    WHEN the '/' page is requested (GET)
    THEN check the response is valid
    """
    response = client.get('/metrics')
    assert response.status_code == 200
