from datetime import datetime, timedelta
import dateutil
import time
import prometheus_client as pc
from sqlalchemy import asc, desc
from flask import (
    render_template,
    flash,
    redirect,
    url_for,
    request,
    g,
    jsonify,
    current_app,
    Response,
)
from app import db, documents
from app.models import (
    Provider,
    Circuit,
    Maintenance,
    MaintCircuit,
    ApschedulerJobs,
    MaintUpdate,
)
from app.main import bp
from app.main.forms import AddCircuitForm, AddCircuitContract, EditCircuitForm
from app.jobs.main import process, failed_messages


# @todo: expose some interesting metrics
MAIN_REQUESTS = pc.Counter(
    'main_page_requests_total', 'total requests for the / route.'
)


@bp.route('/metrics')
def metrics():
    return Response(
        pc.generate_latest(), mimetype='text/plain; version=0.0.4; charset=utf-8'
    )


@bp.route('/', methods=['GET', 'POST'])
def main():
    MAIN_REQUESTS.inc()
    next_run = db.session.query(ApschedulerJobs).filter_by(id='run_loop').first()
    if next_run:
        next_run = datetime.utcfromtimestamp(next_run.next_run_time)
    if request.method == 'POST':
        current_app.apscheduler.add_job(
            id='run_now', replace_existing=True, func=process
        )
        flash('emails are currently being processed')
        return redirect(url_for('main.main'))

    page = request.args.get('page', 1, type=int)
    now = datetime.now().date()
    last_week = now - timedelta(days=7)
    maintenances = (
        MaintCircuit.query.filter(MaintCircuit.date > now)
        .order_by(asc(MaintCircuit.date))
        .paginate(page, current_app.config['POSTS_PER_PAGE'], False)
    )
    recent = (
        MaintCircuit.query.filter(MaintCircuit.date <= now)
        .filter(MaintCircuit.date > last_week)
        .order_by(desc(MaintCircuit.date))
        .all()
    )
    next_url = (
        url_for('main.main', page=maintenances.next_num)
        if maintenances.has_next
        else None
    )
    prev_url = (
        url_for('main.main', page=maintenances.prev_num)
        if maintenances.has_prev
        else None
    )
    return render_template(
        'main.html',
        title='main',
        upcoming=maintenances.items,
        recent=recent,
        prev_url=prev_url,
        next_url=next_url,
        next_run=next_run,
    )


@bp.route('/maintenances', methods=['GET', 'POST'])
def maintenances():
    page = request.args.get('page', 1, type=int)
    maintenances = Maintenance.query.paginate(
        page, current_app.config['POSTS_PER_PAGE'], False
    )
    next_url = (
        url_for('main.maintenances', page=maintenances.next_num)
        if maintenances.has_next
        else None
    )
    prev_url = (
        url_for('main.maintenances', page=maintenances.prev_num)
        if maintenances.has_prev
        else None
    )
    return render_template(
        'maintenances.html',
        title='main',
        maintenances=maintenances.items,
        prev_url=prev_url,
        next_url=next_url,
    )


@bp.route('/providers', methods=['GET', 'POST'])
def providers():
    page = request.args.get('page', 1, type=int)
    providers = Provider.query.paginate(
        page, current_app.config['POSTS_PER_PAGE'], False
    )
    next_url = (
        url_for('main.providers', page=providers.next_num)
        if providers.has_next
        else None
    )
    prev_url = (
        url_for('main.providers', page=providers.prev_num)
        if providers.has_prev
        else None
    )
    return render_template(
        'providers.html',
        title='providers',
        providers=providers.items,
        next_url=next_url,
        prev_url=prev_url,
    )


@bp.route('/circuits', methods=['GET', 'POST'])
def circuits():
    providers = Provider.query.all()
    choices = [(p.id, p.name) for p in providers]
    form = AddCircuitForm()
    form.provider.choices = choices
    if form.validate_on_submit():
        filename = documents.save(request.files['circuit_contract'])
        circuit = Circuit(
            provider_cid=form.provider_cid.data,
            a_side=form.a_side.data,
            z_side=form.z_side.data,
            provider_id=form.provider.data,
            contract_filename=filename,
        )
        db.session.add(circuit)
        db.session.commit()
        flash('circuit added successfully!')
        return redirect(url_for('main.circuits'))

    page = request.args.get('page', 1, type=int)
    circuits = Circuit.query.paginate(page, current_app.config['POSTS_PER_PAGE'], False)
    next_url = (
        url_for('main.circuits', page=circuits.next_num) if circuits.has_next else None
    )
    prev_url = (
        url_for('main.circuits', page=circuits.prev_num) if circuits.has_prev else None
    )
    return render_template(
        'circuits.html',
        title='circuits',
        form=form,
        circuits=circuits.items,
        next_url=next_url,
        prev_url=prev_url,
    )


@bp.route('/maintenances/<maintenance_id>', methods=['GET', 'POST'])
def maintenance_detail(maintenance_id):
    maintenance = Maintenance.query.filter_by(id=maintenance_id).first_or_404()
    updates = MaintUpdate.query.filter_by(maintenance_id=maintenance.id).all()
    page = request.args.get('page', 1, type=int)
    circuits = MaintCircuit.query.filter_by(maint_id=maintenance_id).all()
    return render_template(
        'maintenance_detail.html',
        title='Maintenance Info',
        circuits=circuits,
        maintenance=maintenance,
        updates=updates,
    )


@bp.route('/circuits/<circuit_id>', methods=['GET', 'POST'])
def circuit_detail(circuit_id):
    circuit = Circuit.query.filter_by(id=circuit_id).first_or_404()
    providers = Provider.query.all()
    choices = [(p.id, p.name) for p in providers]
    form = EditCircuitForm()
    form.provider.choices = choices
    if form.validate_on_submit():
        if request.files.get('circuit_contract'):
            filename = documents.save(request.files['circuit_contract'])
            circuit.contract_filename = filename
        circuit.a_side = form.a_side.data
        circuit.z_side = form.z_side.data
        circuit.provider_id = form.provider.data
        db.session.add(circuit)
        db.session.commit()
        flash('circuit updated successfully!')
        return redirect(url_for('main.circuit_detail', circuit_id=circuit_id))
    page = request.args.get('page', 1, type=int)
    maints = (
        MaintCircuit.query.filter_by(circuit_id=circuit_id)
        .order_by(desc(MaintCircuit.date))
        .paginate(page, current_app.config['POSTS_PER_PAGE'], False)
    )
    next_url = (
        url_for('main.circuit_detail', page=maints.next_num, circuit_id=circuit_id)
        if maints.has_next
        else None
    )
    prev_url = (
        url_for('main.circuit_detail', page=maints.prev_num, circuit_id=circuit_id)
        if maints.has_prev
        else None
    )

    return render_template(
        'circuit_detail.html',
        circuit=circuit,
        maints=maints.items,
        next_url=next_url,
        prev_url=prev_url,
        form=form,
    )


@bp.route('/providers/<provider_id>')
def provider_detail(provider_id):
    page = request.args.get('page', 1, type=int)
    provider = Provider.query.filter_by(id=provider_id).first_or_404()
    all_circuits = Circuit.query.filter_by(provider_id=provider_id).all()
    circuits = Circuit.query.filter_by(provider_id=provider_id).paginate(
        page, current_app.config['POSTS_PER_PAGE'], False
    )
    next_url = (
        url_for('main.provider_detail', page=circuits.next_num, provider_id=provider_id)
        if circuits.has_next
        else None
    )
    prev_url = (
        url_for('main.provider_detail', page=circuits.prev_num, provider_id=provider_id)
        if circuits.has_prev
        else None
    )
    return render_template(
        'provider_detail.html',
        circuits=circuits,
        provider=provider,
        next_url=next_url,
        prev_url=prev_url,
        all_circuits=all_circuits,
    )


@bp.route('/failed')
def failed():
    return render_template('failed.html')


@bp.route('/failedmessages')
def failedmessages():
    return failed_messages()
