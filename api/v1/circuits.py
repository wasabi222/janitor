from app.models import Circuit, CircuitSchema, Provider
from flask import make_response, jsonify
from app import db


def read_all():
    """
    This function responds to a request for /circuits
    with the complete lists of circuits

    :return:        sorted list of circuits
    """
    circuits = Circuit.query.all()
    schema = CircuitSchema(many=True)

    return schema.dump(circuits).data


def read_one(circuit_id):
    circuit = Circuit.query.filter(Circuit.id == circuit_id).one_or_none()

    if not circuit:
        text = f'circuit not found for id {circuit_id}'
        return make_response(jsonify(error=404, message=text), 404)

    schema = CircuitSchema()
    data = schema.dump(circuit).data

    return data


def create(circuit):
    """
    creates a circuit! checks to see if the provider_cid is unique and
    that the provider exists.

    :return:        circuit
    """
    provider_cid = circuit.get('provider_cid')
    provider_id = circuit.get('provider_id')
    circuit_exists = Circuit.query.filter(
        Circuit.provider_cid == provider_cid
    ).one_or_none()

    provider_exists = Provider.query.filter(Provider.id == provider_id).one_or_none()

    if circuit_exists:
        text = f'Circuit {provider_cid} already exists'
        return make_response(jsonify(error=409, message=text), 409)

    if not provider_exists:
        text = f'Provider {provider_id} does not exist.' 'Unable to create circuit'
        return make_response(jsonify(error=403, message=text), 403)

    schema = CircuitSchema()
    new_circuit = schema.load(circuit, session=db.session).data

    db.session.add(new_circuit)
    db.session.commit()

    data = schema.dump(new_circuit).data

    return data, 201


def update(circuit_id, circuit):
    """
    updates a circuit!
    :return:        circuit
    """
    c = Circuit.query.filter_by(id=circuit_id).one_or_none()
    if not c:
        text = f'Can not update a circuit that does not exist!'
        return make_response(jsonify(error=409, message=text), 404)

    schema = CircuitSchema()
    update = schema.load(circuit, session=db.session).data

    db.session.merge(update)
    db.session.commit()

    data = schema.dump(c).data

    return data, 201
