from app.models import Maintenance, MaintenanceSchema
from flask import make_response, jsonify
from app import db


def read_all():
    """
    returns all maintenances

    :return:        sorted list of maints
    """

    maints = Maintenance.query.all()
    schema = MaintenanceSchema(many=True)

    return schema.dump(maints).data


def read_one(maintenance_id):
    maint = Maintenance.query.filter(Maintenance.id == maintenance_id).one_or_none()

    if not maint:
        text = f'maintenance not found for id {maintenance_id}'
        return make_response(jsonify(error=404, message=text), 404)

    schema = MaintenanceSchema()
    data = schema.dump(maint).data

    return data
