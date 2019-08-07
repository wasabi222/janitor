from datetime import datetime
from flask import current_app
from app import db, ma
from sqlalchemy import Enum
from marshmallow import fields


PROVIDER_TYPES = Enum(
    'transit',
    'backbone',
    'transport',
    'peering',
    'facility',
    'multi',
    name='ProviderType',
)


class Provider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True)
    type = db.Column(PROVIDER_TYPES)
    email_esc = db.Column(db.VARCHAR(128), nullable=True)
    circuits = db.relationship('Circuit', backref='provider', lazy='dynamic')

    def __repr__(self):
        return f'<Provider {self.name} type: {self.type}>'


class Circuit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider_cid = db.Column(db.VARCHAR(128), index=True, unique=True)
    a_side = db.Column(db.VARCHAR(128), nullable=True)
    z_side = db.Column(db.VARCHAR(128), nullable=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('provider.id'))
    contract_filename = db.Column(db.String(256), default=None, nullable=True)

    def __repr__(self):
        return f'<Circuit {self.provider_cid}>'


class CircuitSchema(ma.ModelSchema):
    class Meta:
        model = Circuit
        sqla_session = db.session
        include_fk = True

    maintenances = fields.Nested('CircuitMaintSchema', default=[], many=True)


class CircuitMaintSchema(ma.ModelSchema):
    maint_id = fields.Int()
    circuit_id = fields.Int()
    impact = fields.Str()
    date = fields.Date()


class Maintenance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider_maintenance_id = db.Column(db.String(128), nullable=True)
    start = db.Column(db.TIME)
    end = db.Column(db.TIME)
    timezone = db.Column(db.String(128), nullable=True)
    cancelled = db.Column(db.INT, default=0)
    rescheduled = db.Column(db.INT, default=0)
    rescheduled_id = db.Column(
        db.Integer, db.ForeignKey('maintenance.id'), nullable=True
    )
    location = db.Column(db.String(2048), index=True, nullable=True)
    reason = db.Column(db.TEXT(), nullable=True)
    received_dt = db.Column(db.DateTime)
    started = db.Column(db.INT, default=0)
    ended = db.Column(db.INT, default=0)
    updates = db.relationship('MaintUpdate', backref='maintenance', lazy='dynamic')

    def __repr__(self):
        return f'<Maintenance {self.provider_maintenance_id}>'


class MaintCircuit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    maint_id = db.Column(db.Integer, db.ForeignKey('maintenance.id'))
    circuit_id = db.Column(db.Integer, db.ForeignKey('circuit.id'))
    impact = db.Column(db.VARCHAR(128))
    date = db.Column(db.DATE)
    maintenance = db.relationship("Maintenance", backref="circuits")
    circuit = db.relationship("Circuit", backref="maintenances")


class MaintUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    maintenance_id = db.Column(db.Integer, db.ForeignKey('maintenance.id'))
    comment = db.Column(db.TEXT())
    updated = db.Column(db.DateTime, default=datetime.utcnow)


class ApschedulerJobs(db.Model):
    id = db.Column(db.VARCHAR(191), primary_key=True)
    next_run_time = db.Column(db.FLOAT)
    job_state = db.Column(db.BLOB, nullable=False)


class MaintenanceSchema(ma.ModelSchema):
    class Meta:
        model = Maintenance
        sqla_session = db.session
        include_fk = True

    circuits = fields.Nested('MaintenanceCircuitSchema', default=[], many=True)


class MaintenanceCircuitSchema(ma.ModelSchema):
    circuit_id = fields.Int()
    impact = fields.Str()
    date = fields.Date()


class ProviderSchema(ma.ModelSchema):
    class Meta:
        model = Provider
        sqla_session = db.session

    circuits = fields.Nested('ProviderCircuitSchema', default=[], many=True)


class ProviderCircuitSchema(ma.ModelSchema):
    id = fields.Int()
    provider_cid = fields.Str()
    a_side = fields.Str()
    z_side = fields.Str()
