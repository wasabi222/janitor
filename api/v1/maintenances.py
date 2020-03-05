from app.models import Maintenance, MaintenanceSchema, MaintCircuit
from flask import make_response, jsonify
from app import db
from datetime import datetime, timedelta
import pytz


def read_all():
    """
    returns all maintenances

    :return:        sorted list of maints
    """

    maints = Maintenance.query.all()
    schema = MaintenanceSchema(many=True)

    return schema.dump(maints).data

def read_one(maintenance_id):
    maint = Maintenance.query.filter(
        Maintenance.id == maintenance_id).one_or_none()

    if not maint:
        text = f'maintenance not found for id {maintenance_id}'
        return make_response(jsonify(error=404, message=text), 404)

    schema = MaintenanceSchema()
    data = schema.dump(maint).data

    return data


def in_progress():
    maints = Maintenance.query.filter(
        Maintenance.started == 1).filter(Maintenance.ended == 0).all()

    schema = MaintenanceSchema(many=True)

    return schema.dump(maints).data


def starting_soon(minutes=5):
    now = datetime.now(tz=pytz.utc)

    starting_soon = []

    # first we get a list of upcoming MaintCircuits, which have the date only

    upcoming = MaintCircuit.query.filter(
       MaintCircuit.date >= now.date(),
       MaintCircuit.date <= (now.date() + timedelta(days=1))
    ).all()

    # now we check the start time in the maintenance to verify

    for maint in upcoming:

        # skip maintenances that have already started
        if maint.maintenance.started:
            continue

        start = datetime.combine(
            maint.date,
            maint.maintenance.start,
            pytz.timezone(maint.maintenance.timezone),
            )
        start_utc = start.astimezone(pytz.utc)

        if start_utc < (now + timedelta(minutes=minutes)):
            starting_soon.append(maint)

    # transform starting_soon
    starting_soon = set(maint.maintenance for maint in starting_soon)

    schema = MaintenanceSchema(many=True)

    return schema.dump(starting_soon).data


def ending_soon(minutes=5):
    now = datetime.now(tz=pytz.utc)

    ending_soon = []

    # first we get a list of upcoming MaintCircuits, which have the date only

    upcoming = MaintCircuit.query.filter(
       MaintCircuit.date >= now.date(),
       MaintCircuit.date <= (now.date() + timedelta(days=1))
    ).all()

    # now we check the end time in the maintenance to verify

    for maint in upcoming:

        # skip maintenances that have already ended
        if maint.maintenance.ended:
            continue

        end = datetime.combine(
            maint.date,
            maint.maintenance.end,
            pytz.timezone(maint.maintenance.timezone),
            )
        end_utc = end.astimezone(pytz.utc)

        if end_utc < (now + timedelta(minutes=minutes)):
            ending_soon.append(maint)

    # transform ending_soon
    ending_soon = set(maint.maintenance for maint in ending_soon)

    schema = MaintenanceSchema(many=True)

    return schema.dump(ending_soon).data
