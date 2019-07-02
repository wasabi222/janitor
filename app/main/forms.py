from flask import request, current_app
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, SelectField
from wtforms.fields.html5 import EmailField
from wtforms.validators import ValidationError, DataRequired, Length, Email
from flask_wtf.file import FileField, FileAllowed, FileRequired
from app.models import Circuit, Provider, PROVIDER_TYPES
from app import documents


class AddCircuitForm(FlaskForm):
    choices = [('placeholder', 'to be replaced in the view func')]
    provider_cid = StringField('provider cid', validators=[DataRequired()])
    a_side = StringField('a side')
    z_side = StringField('z side')
    provider = SelectField('provider', choices=choices, coerce=int)
    circuit_contract = FileField('Circuit Contract',
                                 validators=[
                                 FileAllowed(documents, 'documents only!')])
    submit = SubmitField('submit')

    def validate_provider_cid(self, pcid):
        circuit = Circuit.query.filter_by(
            provider_cid=pcid.data).first()
        if circuit is not None:
           raise ValidationError('this circuit seems to exist!')


class AddCircuitContract(FlaskForm):
    circuit_contract = FileField('Circuit Contract',
                                 validators=[FileRequired(),
                                 FileAllowed(documents, 'documents only!')])
    submit = SubmitField('submit')


class EditCircuitForm(FlaskForm):
    choices = [('placeholder', 'to be replaced in the view func')]
    a_side = StringField('a side')
    z_side = StringField('z side')
    provider = SelectField('provider', choices=choices, coerce=int)
    circuit_contract = FileField('Circuit Contract',
                       validators=[FileAllowed(documents, 'documents only!')])
    submit = SubmitField('submit')
