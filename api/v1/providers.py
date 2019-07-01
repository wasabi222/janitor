from app.models import Circuit, CircuitSchema, Provider, ProviderSchema
from flask import make_response, jsonify
from app import db


def read_all():
    """
    returns all providers

    :return:        list of providers
    """

    providers = Provider.query.all()
    schema = ProviderSchema(many=True)

    return schema.dump(providers).data


def read_one(provider_id):
    """
    returns a single provider

    :return:        dict(Provider)
    """

    provider = Provider.query.filter(Provider.id == provider_id).one_or_none()

    if not provider:
        text = f'provider not found for id {provider_id}'
        return make_response(jsonify(error=404, message=text), 404)

    schema = ProviderSchema()
    data = schema.dump(provider).data

    return data
